"""Automated operational-report scheduler (daily / weekly / monthly 巡检).

In-process asyncio scheduler (same pattern as ``heartbeat.py``) that runs the
existing ``reports.generate(period)`` on a calendar cadence, persists each report
to ES (``.rst_copilot_reports``), and optionally delivers it to a webhook —
turning the on-demand report into a hands-off periodic patrol.

OFF by default. Enable per-period via env:

    RST_REPORT_SCHEDULE              csv of daily / weekly / monthly (empty = off)
    RST_REPORT_WEBHOOK_URL           POST target for each generated report (optional)
    RST_REPORT_WEBHOOK_HEADERS       "K1:V1;K2:V2" (optional)
    RST_REPORT_PERSIST               "0" to skip the ES archive (default on)
    RST_REPORT_INDEX                 archive index (default .rst_copilot_reports)
    RST_REPORT_CHECK_INTERVAL_SECONDS  scheduler tick (default 1800)
    RST_REPORT_TZ                    boundary timezone (default UTC; "+08:00" / "Asia/Shanghai")
    RST_REPORT_CATCHUP_MAX           max missed boundaries to backfill (default 7, 0 = off)

Firing is calendar-boundary based and idempotent: each period fires once per its
boundary (daily=date, weekly=ISO week, monthly=month), evaluated in
``RST_REPORT_TZ``. The last fired boundary is seeded from the ES archive on
start, so a restart won't re-send the same report.

Boundaries missed while the gateway was down are backfilled (newest-last, capped
by RST_REPORT_CATCHUP_MAX) with their own historical window, so a report filed
under Tuesday contains Tuesday's data — not the data from whenever the box came
back up.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone, tzinfo

from . import reports
from .audit_sinks import WebhookSink, _parse_header_pairs, _tls_verify_default
from .es_client import get_es
from .triage import triage_alerts

logger = logging.getLogger("rst.report_scheduler")

DEFAULT_INDEX = ".rst_copilot_reports"
_task: asyncio.Task | None = None
_last_fired: dict[str, str] = {}


def _enabled_periods() -> list[str]:
    raw = os.environ.get("RST_REPORT_SCHEDULE", "")
    out: list[str] = []
    for p in raw.split(","):
        p = p.strip().lower()
        if p in reports.PERIODS and p not in out:
            out.append(p)
        elif p:
            logger.warning("report_schedule_unknown_period", extra={"period": p})
    return out


def _index_name() -> str:
    return os.environ.get("RST_REPORT_INDEX", DEFAULT_INDEX).strip() or DEFAULT_INDEX


# 显式映射。没有它，第一份日报把 boundary_key="2026-09-17" 动态映射成 date，
# 接着周报的 "2026-W38" 写入就是 400 —— 任何 daily+weekly 一起开的部署都会
# 在第一个周期把周报丢掉（2026-09-17 演示机上真发生了）。markdown 正文不需要
# 被检索，关掉索引省一份倒排。
_INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "period": {"type": "keyword"},
            "boundary_key": {"type": "keyword"},
            "status": {"type": "keyword"},
            "claimed_at": {"type": "date"},
            "generated_at": {"type": "date"},
            "start_at": {"type": "date"},
            "end_at": {"type": "date"},
            "license_status": {"type": "keyword"},
            "markdown": {"type": "text", "index": False},
        }
    }
}

_index_ready = False


async def _ensure_index(es) -> None:
    """Create the archive index with the explicit mapping; idempotent. An
    existing index (even one built by dynamic mapping) is left alone."""
    global _index_ready
    if _index_ready:
        return
    try:
        if not await es.indices.exists(index=_index_name()):
            await es.indices.create(index=_index_name(), body=_INDEX_MAPPING)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "resource_already_exists_exception" not in msg:
            logger.warning("report_index_ensure_failed", extra={"error": msg[:200]})
            return
    _index_ready = True


def _check_interval() -> float:
    try:
        v = float(os.environ.get("RST_REPORT_CHECK_INTERVAL_SECONDS", "1800"))
        return v if v >= 60 else 1800.0
    except (TypeError, ValueError):
        return 1800.0


def _persist_enabled() -> bool:
    return os.environ.get("RST_REPORT_PERSIST", "1").strip().lower() not in ("0", "false", "no")


def _report_tz() -> tzinfo:
    """报表日历边界用的时区。

    `RST_REPORT_TZ` 是这一档的覆盖；没设就跟着整个产品的 `RST_TIMEZONE` 走 ——
    以前这里独立回落到 UTC，于是一个只设了 RST_TIMEZONE=+08:00 的部署，提示词和
    额度按东八区切日，日报却在北京时间早上八点出，而没有任何地方说明为什么。
    解析（含 IANA 名字）由 settings.parse_tz 一处负责。
    """
    from . import settings as gw_settings

    raw = (os.environ.get("RST_REPORT_TZ") or "").strip()
    return gw_settings.parse_tz(raw, "RST_REPORT_TZ") if raw else gw_settings.product_tz()


def _boundary_key(period: str, dt: datetime) -> str:
    dt = dt.astimezone(_report_tz())
    if period == "daily":
        return dt.strftime("%Y-%m-%d")
    if period == "weekly":
        return dt.strftime("%G-W%V")  # ISO year-week
    return dt.strftime("%Y-%m")  # monthly


def _boundary_start(period: str, dt: datetime) -> datetime:
    """The local instant the boundary containing ``dt`` began."""
    local = dt.astimezone(_report_tz())
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "daily":
        return midnight
    if period == "weekly":
        return midnight - timedelta(days=midnight.weekday())  # ISO week starts Monday
    return midnight.replace(day=1)


def _catchup_max() -> int:
    try:
        return max(0, int(os.environ.get("RST_REPORT_CATCHUP_MAX", "7")))
    except (TypeError, ValueError):
        return 7


def _pending_boundaries(period: str, last_key: str | None, now: datetime) -> list[tuple[str, datetime]]:
    """Boundaries to fire, oldest first, as ``(key, window_end)``.

    ``window_end`` is None-equivalent for the current boundary (report the last
    ``period`` up to now, as before) and the boundary's own start instant for a
    missed one — which is exactly the window the on-time fire would have used,
    since a boundary's report covers the period BEFORE it.

    With no ``last_key`` (cold start, empty archive) there is nothing to catch up
    on: we have no idea how far back the gap goes, so only the current boundary
    fires.
    """
    current = _boundary_key(period, now)
    if last_key is None or last_key == current:
        return [] if last_key == current else [(current, now)]

    # Walk backwards from the current boundary until we reach the one already
    # fired. Bounded by the catch-up cap so a long outage — or a `last_key` that
    # no longer matches (an RST_REPORT_TZ change) — cannot spawn an unbounded
    # backfill.
    cap = _catchup_max()
    if cap == 0:  # backfill disabled — fire only the current boundary
        return [(current, now)]

    missed: list[tuple[str, datetime]] = []
    cursor = _boundary_start(period, now)
    while len(missed) <= cap:
        prev_start = _boundary_start(period, cursor - timedelta(seconds=1))
        if _boundary_key(period, prev_start) == last_key:
            break
        # window_end = the boundary's own start: a report keyed K has always
        # covered the `delta` BEFORE K (the on-time fire runs just after K
        # begins and looks back). Backfilling with the same rule keeps a
        # recovered report identical to the one that would have been sent.
        missed.append((_boundary_key(period, prev_start), prev_start))
        cursor = prev_start
    if len(missed) > cap:
        missed = missed[:cap]
        logger.warning("report_catchup_truncated",
                       extra={"period": period, "cap": cap, "oldest_kept": missed[-1][0]})
    missed.reverse()  # oldest first
    return missed + [(current, now)]


def _webhook() -> WebhookSink | None:
    url = (os.environ.get("RST_REPORT_WEBHOOK_URL") or "").strip()
    if not url:
        return None
    try:
        return WebhookSink(
            url,
            headers=_parse_header_pairs(os.environ.get("RST_REPORT_WEBHOOK_HEADERS")),
            verify_tls=_tls_verify_default(),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("report_webhook_init_failed", extra={"error": str(e)})
        return None


async def list_archived(period: str | None, limit: int) -> list[dict]:
    """Recent persisted reports (newest first), optionally filtered by period."""
    es = get_es()
    must: list[dict] = []
    if period in reports.PERIODS:
        must.append({"term": {"period": period}})
    # Exclude unfinished pending claim-placeholders — only completed reports.
    query = {
        "bool": {
            "must": must or [{"match_all": {}}],
            "must_not": [{"term": {"status": "pending"}}],
        }
    }
    try:
        resp = await es.search(
            index=_index_name(),
            body={
                "size": max(1, min(limit, 200)),
                "query": query,
                "sort": [{"generated_at": {"order": "desc"}}],
            },
        )
    except Exception:  # noqa: BLE001
        return []
    return [h.get("_source") or {} for h in (resp.body.get("hits") or {}).get("hits") or []]


async def _seed_last_fired(periods: list[str]) -> None:
    """Seed the last fired boundary per period from the ES archive so a restart
    doesn't re-fire a report already produced this period."""
    es = get_es()
    for period in periods:
        try:
            resp = await es.search(
                index=_index_name(),
                body={
                    "size": 1,
                    # Skip pending placeholders — seed only from finished reports.
                    "query": {
                        "bool": {
                            "must": [{"term": {"period": period}}],
                            "must_not": [{"term": {"status": "pending"}}],
                        }
                    },
                    "sort": [{"generated_at": {"order": "desc"}}],
                    "_source": ["boundary_key"],
                },
            )
            hits = (resp.body.get("hits") or {}).get("hits") or []
            if hits:
                key = (hits[0].get("_source") or {}).get("boundary_key")
                if key:
                    _last_fired[period] = key
        except Exception:  # noqa: BLE001
            # No archive index yet / ES unreachable — fire on the next boundary.
            pass


def _triage_index() -> str:
    return (os.environ.get("RST_REPORT_TRIAGE_INDEX") or "").strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


async def _security_section(period: str) -> tuple[str, dict | None]:
    """Optional auto-triage of recent alerts (LLM). Off unless
    RST_REPORT_TRIAGE_INDEX is set. Returns (markdown, summary-dict)."""
    idx = _triage_index()
    if not idx:
        return "", None
    window = int(reports.PERIODS[period][1].total_seconds() // 60)
    try:
        res = await triage_alerts(
            index=idx,
            window_minutes=window,
            max_alerts=_env_int("RST_REPORT_TRIAGE_MAX_ALERTS", 100),
            max_clusters_to_llm=_env_int("RST_REPORT_TRIAGE_MAX_CLUSTERS", 30),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("report_triage_failed", extra={"period": period, "error": str(e)})
        return f"\n## 七、告警分诊巡检\n\n_自动分诊失败：{str(e)[:120]}_\n", None

    clusters = res.get("clusters", [])
    sev_count: dict[str, int] = {}
    for c in clusters:
        s = (c.get("severity") or "info").lower()
        sev_count[s] = sev_count.get(s, 0) + 1
    fp = sum(1 for c in clusters if c.get("is_likely_fp"))

    md = [
        "", "## 七、告警分诊巡检", "",
        f"- 来源：`{idx}` · 窗口 {window} 分钟",
        f"- 告警 {res.get('total_alerts', 0):,} · 聚类 {res.get('total_clusters', 0)} · 已评分 {res.get('scored_clusters', 0)}",
        "- 严重度：" + (" / ".join(f"{k}:{v}" for k, v in sorted(sev_count.items())) or "—"),
        f"- 疑似误报：{fp}",
        "",
    ]
    if res.get("degraded"):
        md += [f"> ⚠️ 评分降级：{str(res.get('degraded_reason', ''))[:160]}", ""]
    top = sorted(clusters, key=lambda c: c.get("priority_rank", 999))[:5]
    if top:
        md += ["| # | 严重度 | 攻击意图 | 主体 | 数量 | 建议 |", "|---:|---|---|---|---:|---|"]
        for c in top:
            subj = f"{c.get('subject_field', '')}={c.get('subject_value', '')}".replace("|", "\\|")[:40]
            rec = (c.get("recommendation") or "—").replace("|", "\\|")[:60]
            md.append(
                f"| {c.get('priority_rank', '?')} | {c.get('severity', '?')} | "
                f"{c.get('attack_intent', '?')} | `{subj}` | {c.get('count', 0)} | {rec} |"
            )
        md.append("")
    summary = {
        "index": idx,
        "window_minutes": window,
        "total_alerts": res.get("total_alerts", 0),
        "total_clusters": res.get("total_clusters", 0),
        "scored_clusters": res.get("scored_clusters", 0),
        "severity_counts": sev_count,
        "likely_fp": fp,
    }
    return "\n".join(md), summary


def _claim_ttl() -> float:
    """How long a ``pending`` claim is honoured before it's treated as a crashed
    (abandoned) lease that another replica may take over. 2× the scheduler tick,
    floored at 1 hour, so a replica that died mid-generation can't permanently
    lose the boundary's report."""
    return max(3600.0, 2 * _check_interval())


def _isoparse(s: object) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


async def _claim(period: str, key: str) -> str | None:
    """Atomically claim this boundary so only ONE replica fires it (multi-replica
    dedup). op_type=create on the report doc id → the loser gets 409.

    赢了返回写进去的那个租约戳（`_release` 靠它认出占位文档还是自己的），输了返回
    None。ES 报错时 fail OPEN、照样发 —— 单机部署上多发一份好过一份都没有 ——
    这时返回的是我们**本来要写的**那个戳：占位文档大概率没落地，`_release` 会因为
    「文档不在 / 状态对不上 / 戳对不上」而什么都不删，正是想要的行为。

    （三态曾经挤在 `str | bool` 里：str=拿到、True=fail open、False=没拿到，调用方
    得先 `if not stamp` 再 `isinstance` 才能用对。少一个态，少一处会写错的地方。）

    The placeholder carries ``claimed_at`` (a lease): if the existing doc is
    still ``pending`` but its lease has expired (the owner crashed before
    persisting), we take it over so the report isn't lost forever."""
    from elasticsearch import ConflictError
    doc_id = f"{period}-{key}"
    now = datetime.now(timezone.utc)
    document = {
        "period": period,
        "boundary_key": key,
        "status": "pending",
        "claimed_at": now.isoformat(),
        "generated_at": now.isoformat(),
    }
    es = get_es()
    await _ensure_index(es)
    try:
        await es.index(
            index=_index_name(),
            id=doc_id,
            document=document,
            op_type="create",
            refresh=False,
        )
        return str(document["claimed_at"])
    except ConflictError:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning("report_claim_error", extra={"period": period, "error": str(e)})
        return str(document["claimed_at"])  # fail open：照样发，戳给出去让 _release 自己判

    # A doc already exists for this boundary. Take it over only if it's a stale
    # pending lease (crashed owner); a completed report or a live lease → skip.
    try:
        existing = await es.get(index=_index_name(), id=doc_id)
        src = existing.body.get("_source") or {}
        if src.get("status") != "pending":
            return None  # already completed by someone
        claimed_at = _isoparse(src.get("claimed_at"))
        if claimed_at is not None and (now - claimed_at).total_seconds() < _claim_ttl():
            return None  # lease still live — another replica owns it
        # Stale (or missing/unparseable) lease → take it over. Overwrite under
        # optimistic concurrency (if_seq_no/if_primary_term from the get above) so
        # that if another replica took the same stale lease first, our write hits
        # a 409 and we back off — otherwise both would overwrite and each emit a
        # duplicate report for this boundary.
        try:
            await es.index(
                index=_index_name(),
                id=doc_id,
                document=document,
                if_seq_no=existing.body.get("_seq_no"),
                if_primary_term=existing.body.get("_primary_term"),
                refresh=False,
            )
            return str(document["claimed_at"])
        except ConflictError:
            return None  # another replica won the takeover — give up
    except Exception as e:  # noqa: BLE001
        logger.warning("report_claim_error", extra={"period": period, "error": str(e)})
        return None


async def _release(period: str, key: str, claimed_at: str | None) -> None:
    """Release a claim (so the boundary retries) when generation failed.

    只删「还是 pending、而且租约戳正是我们自己写的那一个」的占位文档，并且带 CAS。
    原来是无条件 delete：租约超时被另一个副本接管、甚至那边已经把完整报告写进去
    之后，我们这一次的失败清理照样会把它删掉 —— 删掉的是别人的报告。

    `claimed_at is None` 表示 claim 那一步 ES 就报错了（我们是 fail open 发的），
    没有哪个占位文档是我们的，什么都不该删。
    """
    if claimed_at is None:
        return
    es = get_es()
    doc_id = f"{period}-{key}"
    try:
        cur = await es.get(index=_index_name(), id=doc_id)
        src = cur.body.get("_source") or {}
        if src.get("status") != "pending" or src.get("claimed_at") != claimed_at:
            logger.info("report_release_skipped",
                        extra={"period": period, "boundary_key": key,
                               "status": src.get("status")})
            return
        await es.delete(index=_index_name(), id=doc_id, refresh=False,
                        if_seq_no=cur.body.get("_seq_no"),
                        if_primary_term=cur.body.get("_primary_term"))
    except Exception:  # noqa: BLE001
        pass


async def _fire(period: str, key: str, window_end: datetime | None = None) -> bool:
    """Generate + archive + deliver one report. Returns False only when nothing
    was produced (generation raised), so the loop can retry on the next tick
    instead of marking the boundary done.

    ``window_end`` is set when backfilling a boundary missed during downtime, so
    the report covers that boundary's period instead of the last 24h/7d/30d
    before restart."""
    # Multi-replica dedup: claim the boundary before doing the work. Only when
    # persisting (the claim needs the ES doc); without persistence there's no
    # shared state to dedup on.
    claimed = False
    claimed_at: str | None = None
    if _persist_enabled():
        claimed_at = await _claim(period, key)
        if claimed_at is None:
            logger.info("report_skip_claimed", extra={"period": period, "boundary_key": key})
            return True  # another replica owns this boundary — done, don't retry
        claimed = True

    try:
        report = await reports.generate(period, include_health=True, end=window_end)
    except Exception as e:  # noqa: BLE001
        if claimed:
            await _release(period, key, claimed_at)
        logger.warning("report_generate_failed", extra={"period": period, "error": str(e)})
        return False

    # Optional security inspection (auto-triage). Appends to the markdown.
    # Skipped on a backfill: triage_alerts only takes a window relative to NOW,
    # so running it here would staple today's alerts onto a report for a past
    # boundary — silently wrong in the one section an operator acts on.
    if window_end is None:
        sec_md, sec_summary = await _security_section(period)
        if sec_md:
            report["markdown"] = report.get("markdown", "") + sec_md
        if sec_summary is not None:
            report["security_triage"] = sec_summary

    if _persist_enabled():
        try:
            es = get_es()
            await _ensure_index(es)
            await es.index(
                index=_index_name(),
                id=f"{period}-{key}",  # idempotent per boundary
                document={
                    "period": period,
                    "boundary_key": key,
                    "status": "complete",  # overwrites the pending claim placeholder
                    "generated_at": report["generated_at"],
                    "start_at": report["start_at"],
                    "end_at": report["end_at"],
                    "license_status": report.get("license_status"),
                    "summary": report.get("summary"),
                    "health": report.get("health"),
                    "security_triage": report.get("security_triage"),
                    "markdown": report.get("markdown"),
                },
            )
        except Exception as e:  # noqa: BLE001
            # The body never landed — don't mark the boundary done. Release the
            # claim so the next tick retries instead of archiving an empty shell.
            logger.warning("report_persist_failed", extra={"period": period, "error": str(e)})
            if claimed:
                await _release(period, key, claimed_at)
            return False

    sink = _webhook()
    if sink is not None:
        # Legacy generic webhook (raw JSON). WebhookSink.write never raises.
        await sink.write({"type": "operational_report", "boundary_key": key, **report})

    # Feishu delivery via the durable outbox (rendered card + retry). Best-effort:
    # a dispatch failure must not fail the report (it's already archived).
    try:
        from .notify import outbox
        n = await outbox.dispatch_report(report, key)
        if n:
            logger.info("report_dispatched", extra={"period": period, "targets": n})
    except Exception as e:  # noqa: BLE001
        logger.warning("report_dispatch_failed", extra={"period": period, "error": str(e)})

    logger.info("report_fired", extra={"period": period, "boundary_key": key})
    return True


async def _loop() -> None:
    logger.info(
        "report_scheduler_started",
        extra={"periods": _enabled_periods(), "interval_s": _check_interval()},
    )
    # 已经从归档里认过位的周期。每轮重读配置，所以 RST_REPORT_SCHEDULE 改了不用
    # 重启（告警接入一直是这个行为，这里之前要重启，两个同类特性说法不一）；
    # 新冒出来的周期必须先 seed，否则 `_last_fired` 是空的，会被当成冷启动，
    # 把这一档已经归档过的当期报告再发一遍。
    seeded: set[str] = set()
    while True:
        try:
            now = datetime.now(timezone.utc)
            periods = _enabled_periods()
            unseen = [p for p in periods if p not in seeded]
            if unseen:
                await _seed_last_fired(unseen)
                seeded.update(unseen)
            for period in periods:
                current = _boundary_key(period, now)
                for key, window_end in _pending_boundaries(period, _last_fired.get(period), now):
                    # Only mark the boundary done when a report was actually
                    # produced — a transient ES/LLM outage retries next tick.
                    is_current = key == current
                    if not await _fire(period, key, None if is_current else window_end):
                        break  # keep the gap; the next tick retries from here
                    _last_fired[period] = key
            await asyncio.sleep(_check_interval())
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001
            logger.exception("report_scheduler_loop_error")
            await asyncio.sleep(_check_interval())


def start() -> None:
    """常驻空转，直到有周期被配上 —— 和告警接入的 start() 同一套。

    原来是「启动时没配就不起」，于是配上 RST_REPORT_SCHEDULE 必须重启网关才生效，
    而同样是后台巡检的告警接入不用。空转的代价是每 `RST_REPORT_CHECK_INTERVAL_SECONDS`
    醒一次、读一个环境变量。
    """
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
