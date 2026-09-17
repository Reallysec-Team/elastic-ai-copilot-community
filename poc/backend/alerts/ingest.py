"""Source A — poll tail of the Kibana/ES detection-alerts index.

Each tick queries ``@timestamp > cursor`` (sorted asc, bounded batch), normalizes
+ stores + fans out each new alert, then advances a persisted cursor. Range+cursor
tailing (not PIT) is the robust ES pattern for an unbounded live feed; dedup by
alert_id absorbs same-timestamp ties. Off unless ``RST_ALERT_INGEST_INDEX`` is set.

Shared entry point ``handle_new_alert`` is reused by source B (webhook) so both
sources store, stream, and dispatch through one path.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from ..es_client import get_es
from ..index_whitelist import get as get_whitelist
from . import broker, store
from .summarize import summarize as summarize_alert

logger = logging.getLogger("rst.alerts.ingest")

_CURSOR_INDEX = ".rst_copilot_cursors"
_CURSOR_ID = "alert_ingest"
_BATCH = 200
# Pages of _BATCH to drain in one tick before yielding. Bounds the work a
# single tick can do (a backlog is drained across ticks) while still letting a
# burst larger than one page through — the cap exists so a huge backlog cannot
# monopolise the loop, not to limit total ingestion.
_MAX_PAGES_PER_TICK = 10
_task: asyncio.Task | None = None


def _source_index() -> str:
    return (os.environ.get("RST_ALERT_INGEST_INDEX") or "").strip()


def _interval() -> float:
    try:
        v = float(os.environ.get("RST_ALERT_INGEST_INTERVAL_SECONDS", "10"))
        return v if v >= 3 else 10.0
    except (TypeError, ValueError):
        return 10.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def summary_concurrency() -> int:
    """一次推送里同时处理几条。每条要过一次 LLM（摘要），串行跑 200 条能到几分钟。"""
    try:
        v = int(os.environ.get("RST_ALERT_INGEST_CONCURRENCY", "4"))
    except (TypeError, ValueError):
        return 4
    return v if 1 <= v <= 32 else 4


def _cold_start_gte() -> str:
    """Lower bound for the very first tick (no cursor yet). Default = last hour.

    RST_ALERT_INGEST_LOOKBACK (e.g. ``24h``, ``7d``) widens it: a site that
    turns ingest on with weeks of existing detections wants them, and a demo
    seeded with a day-old attack chain never showed a single alert because the
    seeds sat outside the fixed hour. Only ever consulted on cold start."""
    raw = os.environ.get("RST_ALERT_INGEST_LOOKBACK", "").strip()
    if raw and re.fullmatch(r"\d+[smhdw]", raw):
        return f"now-{raw}"
    if raw:
        logger.warning("alert_ingest_lookback_invalid", extra={"value": raw})
    return "now-1h"


def summary_budget_s() -> float:
    """摘要的时间预算。超了之后剩下的告警照旧入库/推流/派发，只是不再花 LLM ——
    Kibana connector 有自己的超时，请求拖过去它会重发同一批，而重发的代价是整批
    再走一遍。丢摘要好过丢告警，更好过无限重试。"""
    try:
        v = float(os.environ.get("RST_ALERT_INGEST_BUDGET_S", "20"))
    except (TypeError, ValueError):
        return 20.0
    return v if v > 0 else 20.0


# 最近一段时间里因为超出摘要预算而没生成摘要的条数。只在内存里 —— 它是给运维看
# 「刚才那批为什么没摘要」的即时线索，不是要长期留存的指标；重启清零可以接受。
_SKIP_WINDOW_S = 3600.0
_summary_skipped: list[float] = []


def _note_summary_skipped() -> None:
    now = time.time()
    _summary_skipped.append(now)
    cutoff = now - _SKIP_WINDOW_S
    while _summary_skipped and _summary_skipped[0] < cutoff:
        _summary_skipped.pop(0)


def summary_skipped_recent() -> int:
    """最近一小时跳过了多少条摘要。"""
    cutoff = time.time() - _SKIP_WINDOW_S
    return sum(1 for t in _summary_skipped if t >= cutoff)


async def handle_new_alert(alert: dict[str, Any], *, summarize: bool = True) -> bool:
    """Store (deduped) → stream → dispatch to Feishu. Returns True if new.

    Shared by both ingest sources. Dispatch is best-effort; masking for external
    egress happens inside ``outbox.dispatch_alert``.

    ``summarize=False`` 时跳过那一次 LLM，告警照旧入库/推流/派发，只是没有摘要，
    并且在文档上留一个 ``summary_skipped`` 标记 —— 否则「跳过了」和「摘要功能关着」
    「这条本来就没主体」在界面上长得一模一样。
    webhook 那条路在超出预算之后用它 —— 一次推送最多带 200 条告警，每条一次 LLM
    串下来能跑几分钟，connector 超时重发，于是同一批再来一遍。丢摘要好过丢告警。
    """
    # Duplicates must not reach the LLM. The summary has to be generated BEFORE
    # store_alert so it lands in the single create write — but store_alert is
    # also the dedup, so without this pre-check every boundary re-read (once per
    # tick, by design) and every webhook retry paid for a summary that was then
    # thrown away with the duplicate.
    if await store.exists(alert.get("alert_id") or ""):
        return False
    # One-sentence AI summary (default on, best-effort, masked before LLM). Done
    # before store so it persists + rides the SSE/Feishu payloads.
    if summarize and not alert.get("summary"):
        alert["summary"] = await summarize_alert(alert)
    elif not alert.get("summary"):
        alert["summary_skipped"] = True
        _note_summary_skipped()
    is_new = await store.store_alert(alert)
    if not is_new:
        return False
    broker.publish(alert)
    try:
        from ..notify import outbox
        ref = alert.get("alert_id") or ""
        await outbox.dispatch_alert(alert, ref)
    except Exception as e:  # noqa: BLE001
        logger.warning("alert_dispatch_failed", extra={"error": str(e)})
    return True


# ---- cursor persistence --------------------------------------------------

class CursorUnavailable(Exception):
    """The cursor could not be READ — distinct from "there is no cursor yet"."""


async def _load_cursor() -> str | None:
    """Cursor timestamp, or None for a genuine cold start.

    Raises CursorUnavailable for anything that is not a clean 404. Collapsing
    the two meant a cursor index that became unreadable (permissions change,
    ILM deletion, transient fault) silently reset the tail to `now-1h` on every
    tick while the source index still read fine — losing everything older than
    an hour that had not been stored yet, with `status()` reporting
    `cursor_ts: null`, which looks like "not started".
    """
    from elasticsearch import NotFoundError

    try:
        resp = await get_es().get(index=_CURSOR_INDEX, id=_CURSOR_ID)
        return (resp.body.get("_source") or {}).get("last_ts")
    except NotFoundError:
        return None  # cold start: no cursor written yet
    except Exception as e:  # noqa: BLE001
        raise CursorUnavailable(str(e)) from e


async def _save_cursor(last_ts: str) -> None:
    try:
        await get_es().index(index=_CURSOR_INDEX, id=_CURSOR_ID,
                              document={"last_ts": last_ts, "updated_at": _now_iso()},
                              refresh=False)
    except Exception as e:  # noqa: BLE001
        logger.warning("cursor_save_failed", extra={"error": str(e)})


# ---- tail ----------------------------------------------------------------

async def tick() -> int:
    """One tail pass. Returns count of new alerts ingested. Exposed for tests."""
    index = _source_index()
    if not index:
        return 0
    if not get_whitelist().is_allowed(index):
        logger.warning("ingest_index_not_whitelisted", extra={"index": index})
        return 0

    try:
        cursor = await _load_cursor()
    except CursorUnavailable as e:
        # A cursor we cannot READ is not the same as no cursor. Treating a 403 /
        # connection error as a cold start silently resets the tail to a 1-hour
        # window on every tick, and anything older than an hour that was not yet
        # stored is lost for good. Skip the tick instead; the next one retries.
        logger.warning("ingest_cursor_unavailable", extra={"error": str(e)})
        return 0

    gte = cursor or _cold_start_gte()  # cold start window, then advance from cursor
    es = get_es()
    new_count = 0
    max_ts = cursor
    search_after: list | None = None
    pages = 0

    # Paginate WITHIN the tick with search_after. `gte` alone is not enough: if
    # more than _BATCH alerts share the boundary timestamp, a single-page tick
    # would re-read the same page forever and never advance. Sorting by
    # (@timestamp, _doc) gives a total order to page through.
    while pages < _MAX_PAGES_PER_TICK:
        body: dict[str, Any] = {
            "size": _BATCH,
            # INCLUSIVE lower bound, deliberately. With `gt`, a group of alerts
            # sharing one @timestamp that straddles the _BATCH cap is lost
            # forever: the cursor advances to that timestamp and the remainder
            # is excluded from every future query. One Kibana rule execution
            # writing 205 signals whose last 10 share a millisecond is enough.
            # `gte` re-reads the boundary timestamp, and store_alert's
            # op_type=create absorbs the duplicates — which is what this
            # module's own docstring always claimed the design was.
            "query": {"range": {"@timestamp": {"gte": gte}}},
            "sort": [{"@timestamp": {"order": "asc"}}, {"_doc": {"order": "asc"}}],
        }
        if search_after is not None:
            body["search_after"] = search_after
        try:
            resp = await es.search(index=index, body=body)
        except Exception as e:  # noqa: BLE001
            logger.warning("ingest_search_failed", extra={"index": index, "error": str(e)})
            break

        hits = (resp.body.get("hits") or {}).get("hits") or []
        if not hits:
            break
        pages += 1

        for h in hits:
            src = h.get("_source") or {}
            # Record the index we QUERIED (the configured alias), not `_index`
            # from the hit. Reading `.alerts-security.alerts-default` returns
            # its current backing index,
            # `.internal.alerts-security.alerts-default-000015` — a name that
            # changes on every rollover. Storing that pins the alert (and its
            # Kibana deep-link, and any follow-up investigation query) to an
            # index that will not exist under that name for long. The alias is
            # stable and is what a Kibana data view is created against.
            alert = store.normalize(src, doc_id=h.get("_id"), origin="poll",
                                    source_index=index, source_id=h.get("_id"))
            if await handle_new_alert(alert):
                new_count += 1
            ts = alert.get("@timestamp")
            if ts and (max_ts is None or str(ts) > str(max_ts)):
                max_ts = ts

        if len(hits) < _BATCH:
            break
        sort_vals = hits[-1].get("sort")
        if not sort_vals:  # index without the expected sort → stop rather than loop
            break
        search_after = list(sort_vals)
    else:
        # Hit the page cap with more waiting; the next tick resumes from the
        # cursor. Visible, because silently capped ingestion looks like a quiet
        # cluster.
        logger.warning("ingest_page_cap_reached",
                       extra={"index": index, "pages": pages, "new": new_count})

    if max_ts and max_ts != cursor:
        await _save_cursor(str(max_ts))
    if new_count:
        logger.info("ingest_tick", extra={"index": index, "new": new_count, "pages": pages})
    return new_count


async def status() -> dict[str, Any]:
    """Live ingest posture for the GUI: source A index/interval + whether the
    poll tail is active, source B webhook enablement, and the tail cursor."""
    index = _source_index()
    return {
        "index": index,
        "interval": _interval(),
        "enabled": bool(index),
        "whitelisted": (not index) or get_whitelist().is_allowed(index),
        "webhook_enabled": bool((os.environ.get("RST_ALERT_WEBHOOK_SECRET") or "").strip()),
        "cursor_ts": await _load_cursor(),
        # 「最近一小时有多少条没摘要」+ 那两个决定它的旋钮。没有这个的话，运维看到
        # 一批告警突然没摘要，无从判断是关掉了、失败了、还是撞上了预算。
        "summary_skipped_recent": summary_skipped_recent(),
        "summary_budget_s": summary_budget_s(),
        "summary_concurrency": summary_concurrency(),
    }


async def _loop() -> None:
    logger.info("alert_ingest_started", extra={"interval_s": _interval()})
    while True:
        try:
            await tick()  # no-op when no index configured (runtime GUI toggle)
            await asyncio.sleep(_interval())
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001
            logger.exception("alert_ingest_loop_error")
            await asyncio.sleep(_interval())


def start() -> None:
    """Always runs; the loop idles (tick no-ops) until RST_ALERT_INGEST_INDEX is
    set. Kept always-on so the GUI can enable source A at runtime without a
    gateway restart — settings.save patches the env, next tick picks it up."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
