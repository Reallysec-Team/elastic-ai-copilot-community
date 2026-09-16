"""Delivery outbox: durable, retrying, deduped Feishu delivery.

One ES doc per (producer ref × target) in ``.rst_copilot_deliveries``. Producers
(report scheduler, alert ingest) enqueue; a single in-process worker claims due
jobs, sends via ``feishu.send``, and retries with exponential backoff, dead-
lettering after ``max_attempts``. Enqueue is idempotent (op_type=create on a
deterministic id) so a restart or duplicate fire never double-delivers.

Delivery is decoupled from generation: a Feishu outage backs off here without
blocking or losing the report/alert.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ..api_errors import ApiError
from ..es_client import get_es
from . import channels, config, payload as payload_mod, secret_box
# 派发已经走 channels 了，这里仍然导入飞书模块：既有测试通过 `outbox.feishu.send`
# 打桩（模块对象是同一个，打在这儿等于打在 channels 用的那个上）。
from . import feishu  # noqa: F401
from .errors import ChannelError

logger = logging.getLogger("rst.notify.outbox")

DEFAULT_INDEX = ".rst_copilot_deliveries"
MAX_ATTEMPTS = 6
_BASE_BACKOFF = 30.0   # seconds
_MAX_BACKOFF = 3600.0
_BATCH = 20
# How long a claim is honoured before another tick may take the job back.
# Longer than any plausible Feishu round-trip, short enough that a restart
# during a send delays the card by seconds rather than losing it.
_CLAIM_LEASE_S = float(os.environ.get("RST_NOTIFY_CLAIM_LEASE_S", "").strip() or 120)

_task: asyncio.Task | None = None
_index_ready = False


def _index() -> str:
    return (os.environ.get("RST_NOTIFY_DELIVERIES_INDEX") or DEFAULT_INDEX).strip() or DEFAULT_INDEX


def _interval() -> float:
    try:
        v = float(os.environ.get("RST_NOTIFY_WORKER_INTERVAL_SECONDS", "15"))
        return v if v >= 5 else 15.0
    except (TypeError, ValueError):
        return 15.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _backoff_seconds(attempts: int) -> float:
    # 30s, 60, 120, ... capped; +/-15% jitter so retries don't thundering-herd.
    raw = min(_BASE_BACKOFF * (2 ** max(0, attempts - 1)), _MAX_BACKOFF)
    # 真随机源。原来拿 time.time() 当伪随机：同一毫秒内算出的抖动完全相同，而
    # 「一批投递同时失败」正是抖动唯一要拆开的场景 —— 等于没有抖动。
    jitter = raw * random.uniform(-0.15, 0.15)
    return max(5.0, raw + jitter)


async def _ensure_index() -> None:
    global _index_ready
    if _index_ready:
        return
    es = get_es()
    try:
        if not await es.indices.exists(index=_index()):
            await es.indices.create(index=_index(), body={
                "mappings": {
                    "properties": {
                        "kind": {"type": "keyword"},
                        # 投递渠道（feishu / email / …）。老文档没有这个字段，
                        # 读的时候按 feishu 兜底 —— 那时只有这一个渠道。
                        "channel": {"type": "keyword"},
                        "ref": {"type": "keyword"},
                        "target_id": {"type": "keyword"},
                        "status": {"type": "keyword"},
                        "attempts": {"type": "integer"},
                        "next_attempt_at": {"type": "date"},
                        # 租约戳。不声明的话它只能靠动态映射长出来，而 _due_jobs
                        # 的 range 查询要按 date 比较 —— 映射先到，语义才稳。
                        "claimed_at": {"type": "date"},
                        "created_at": {"type": "date"},
                        "updated_at": {"type": "date"},
                        "sent_at": {"type": "date"},
                        "last_error": {"type": "text"},
                        # card body: store but don't index its arbitrary shape
                        "body": {"type": "object", "enabled": False},
                    }
                }
            })
        _index_ready = True
    except Exception as e:  # noqa: BLE001
        logger.warning("deliveries_index_ensure_failed", extra={"error": str(e)})


async def enqueue(kind: str, ref: str, target: dict[str, Any], body: dict[str, Any]) -> bool:
    """Queue one delivery. id = ``{kind}:{ref}:{target_id}`` (idempotent). Stores
    the encrypted secret, never plaintext. Returns True if newly queued."""
    from elasticsearch import ConflictError
    await _ensure_index()
    tid = target.get("id") or "?"
    doc_id = f"{kind}:{ref}:{tid}"
    now = _now().isoformat()
    document = {
        "kind": kind,
        "channel": (target.get("channel") or "feishu"),
        "ref": ref,
        "target_id": tid,
        "target_name": target.get("name"),
        # 投递文档跟配置一样只存密文：企业微信 / Slack / Teams 的鉴权就是 URL
        # 里那个 key，而投递记录是要在界面上列出来的。
        "webhook_url_enc": secret_box.encrypt(str(target.get("webhook_url") or "")),
        "secret_enc": target.get("secret_enc", ""),
        # 邮件目标没有 webhook，收件人跟着投递走 —— 之后改了目标的收件人，
        # 已经排队的那封仍按当初的名单发，跟 webhook_url 的语义一致。
        "recipients": target.get("recipients") or [],
        "body": body,
        "status": "queued",
        "attempts": 0,
        "max_attempts": MAX_ATTEMPTS,
        "next_attempt_at": now,
        "created_at": now,
        "updated_at": now,
        "last_error": "",
    }
    try:
        await get_es().index(index=_index(), id=doc_id, document=document,
                              op_type="create", refresh=False)
        return True
    except ConflictError:
        return False  # already queued/delivered for this ref+target
    except Exception as e:  # noqa: BLE001
        logger.warning("enqueue_failed", extra={"id": doc_id, "error": str(e)})
        return False


# ---- producer dispatch helpers ------------------------------------------

async def dispatch_report(report: dict[str, Any], boundary_key: str) -> int:
    """Render + enqueue a report to every target bound to its period."""
    period = report.get("period", "")
    targets = await config.targets_for_period(period)
    if not targets:
        return 0
    base_url = (os.environ.get("RST_PUBLIC_BASE_URL") or "").strip()
    ref = f"{period}-{boundary_key}"
    # 生产者只产一次中立事件；「长什么样」是渠道的事。
    event = payload_mod.from_report(report, base_url=base_url)
    n = 0
    for t in targets:
        body = channels.render(t.get("channel"), event)
        if await enqueue("report", ref, t, body):
            n += 1
    return n


def mask_alert_for_egress(alert: dict[str, Any]) -> dict[str, Any]:
    """Mask an alert for EXTERNAL delivery (Feishu / 邮件). The normalized alert carries
    its subject under a generic key (``subject_value``), so ``mask_doc`` can't
    classify it by its real field name — a plain username/hostname (not IP/email-
    shaped) would slip through unmasked. Re-mask the subject using its real field
    path (host.name / user.name / source.ip) as the key so the right category
    applies. Airgapped mode passes through (mask_doc is a no-op there)."""
    from ..field_masking import mask_doc
    safe = mask_doc(alert)
    sf = alert.get("subject_field")
    sv = alert.get("subject_value")
    if sf and sv:
        safe = {**safe, "subject_value": mask_doc({sf: sv}).get(sf, sv)}
    return safe


async def dispatch_alert(alert: dict[str, Any], ref: str) -> int:
    """Render + enqueue an alert to targets whose threshold it meets. 投递目标都在
    产品之外（飞书服务器、客户的邮件服务器），所以渲染前先按脱敏档处理主体值
    （cloud 遮 IP/主机名；airgapped 直通）。"""
    targets = await config.targets_for_alert(alert.get("severity", "info"))
    if not targets:
        return 0
    safe = mask_alert_for_egress(alert)
    base_url = (os.environ.get("RST_PUBLIC_BASE_URL") or "").strip()
    event = payload_mod.from_alert(safe, base_url=base_url)
    n = 0
    for t in targets:
        body = channels.render(t.get("channel"), event)
        if await enqueue("alert", ref, t, body):
            n += 1
    return n


# ---- worker --------------------------------------------------------------

async def _due_jobs() -> list[dict[str, Any]]:
    es = get_es()
    now = _now()
    now_iso = now.isoformat()
    # Deliveries whose claim has expired are due again. Without this a job that
    # was `sending` when the gateway went down (deploy, OOM, docker stop) stayed
    # `sending` FOREVER: only _deliver moved it out, and _deliver never ran
    # again. asyncio cancellation on shutdown raises CancelledError, which is a
    # BaseException and so slipped past _deliver's `except Exception` — the
    # critical-alert card simply never reached the Feishu group, the delivery
    # list showed `sending` indefinitely, and there was no dead-letter to look
    # in. report_scheduler._claim already had exactly this lease takeover.
    stale_before = (now - timedelta(seconds=_CLAIM_LEASE_S)).isoformat()
    try:
        resp = await es.search(index=_index(), body={
            "size": _BATCH,
            "seq_no_primary_term": True,
            "query": {"bool": {"should": [
                {"bool": {"must": [
                    {"terms": {"status": ["queued", "failed"]}},
                    {"range": {"next_attempt_at": {"lte": now_iso}}},
                ]}},
                {"bool": {"must": [
                    {"term": {"status": "sending"}},
                    {"range": {"claimed_at": {"lt": stale_before}}},
                ]}},
                # 租约代码上线前卡在 sending 的老文档根本没有 claimed_at，而 ES 的
                # range 不匹配缺字段的文档 —— 上面那条救不到它们，正是这段注释说
                # 要治的病。没有戳就没有租约，直接算过期。
                {"bool": {
                    "must": [{"term": {"status": "sending"}}],
                    "must_not": [{"exists": {"field": "claimed_at"}}],
                }},
            ], "minimum_should_match": 1}},
            "sort": [{"next_attempt_at": {"order": "asc"}}],
        })
    except Exception:  # noqa: BLE001 — index missing / ES down → nothing due
        return []
    return (resp.body.get("hits") or {}).get("hits") or []


async def _claim(hit: dict[str, Any]) -> bool:
    """Optimistically flip queued/failed → sending so only one replica sends it."""
    from elasticsearch import ConflictError
    src = hit["_source"]
    src["status"] = "sending"
    # Lease stamp: this is what lets a later tick reclaim the job if this
    # process dies mid-send. Without it `sending` is a terminal state by
    # accident.
    src["claimed_at"] = _now().isoformat()
    src["updated_at"] = src["claimed_at"]
    try:
        resp = await get_es().index(
            index=_index(), id=hit["_id"], document=src,
            if_seq_no=hit["_seq_no"], if_primary_term=hit["_primary_term"], refresh=False)
        # Carry the post-claim version forward so _finish can write under the
        # same CAS. Dropping it here is what let a timed-out sender overwrite a
        # delivery that another replica had already completed.
        #
        # 真 ES 一定回新版本号。读不到就放弃这次 claim：没有版本号 = _finish 那边
        # 的 CAS 变成空 dict = 终态写入无保护覆盖，恰恰是「超时的 sender 复活已投
        # 递任务」要防的事。文档此刻已是 sending 且带了 claimed_at，下一轮租约到期
        # 会重新捡起来 —— 晚一个租约，好过丢掉保护继续发。
        new_seq = resp.get("_seq_no") if hasattr(resp, "get") else None
        new_term = resp.get("_primary_term") if hasattr(resp, "get") else None
        if new_seq is None or new_term is None:
            logger.warning("claim_no_version", extra={"id": hit["_id"]})
            return False
        hit["_seq_no"] = new_seq
        hit["_primary_term"] = new_term
        return True
    except ConflictError:
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("claim_failed", extra={"id": hit["_id"], "error": str(e)})
        return False


_URL_TAIL = re.compile(r"(https?://[^/\s]+)\S*")


def _scrub(text: object, limit: int = 200) -> str:
    """错误文本里的 webhook URL 要抹掉路径和查询串再落地。

    对飞书 / Slack / 企业微信来说，webhook 的路径本身就是凭据（所以 URL 是
    加密存的、不出接口）。而底层 httpx 的异常消息里常常带着完整 URL —— 那条
    error 不只进日志，还写进 outbox 文档，再由 /api/notify/deliveries 回到
    界面上。留 scheme + 主机足够定位问题，后面那截不留。
    """
    return _URL_TAIL.sub(r"\1/…", str(text))[:limit]


async def _finish(doc_id: str, src: dict[str, Any], *, ok: bool, error: str = "",
                  retryable: bool = False,
                  seq_no: int | None = None, primary_term: int | None = None) -> None:
    """Write the terminal state under the claim's CAS.

    Without the CAS this was a blind overwrite of whatever the document had
    become. A sender that overran its lease would come back — after another
    replica had already reclaimed the job and delivered it — and stamp its own
    stale snapshot on top: `sent` reverted to `failed`, `next_attempt_at` pushed
    into the future, and the alert went out a second time. Losing the CAS now
    means the job is no longer ours; the owner writes the real outcome.
    """
    from elasticsearch import ConflictError

    now = _now()
    src["updated_at"] = now.isoformat()
    if ok:
        src["status"] = "sent"
        src["sent_at"] = now.isoformat()
        src["last_error"] = ""
    else:
        src["attempts"] = int(src.get("attempts", 0)) + 1
        src["last_error"] = error[:400]
        if not retryable or src["attempts"] >= int(src.get("max_attempts", MAX_ATTEMPTS)):
            src["status"] = "dead"
        else:
            src["status"] = "failed"
            next_at = now.timestamp() + _backoff_seconds(src["attempts"])
            src["next_attempt_at"] = datetime.fromtimestamp(next_at, tz=timezone.utc).isoformat()
    cas: dict[str, Any] = {}
    if seq_no is not None and primary_term is not None:
        cas = {"if_seq_no": seq_no, "if_primary_term": primary_term}
    try:
        await get_es().index(index=_index(), id=doc_id, document=src,
                              refresh=False, **cas)
    except ConflictError:
        # Lease was taken over mid-send. Whoever holds it now owns the outcome —
        # writing ours would resurrect or duplicate the delivery.
        logger.warning("finish_lost_claim", extra={"id": doc_id, "would_be": src.get("status")})
    except Exception as e:  # noqa: BLE001
        logger.warning("finish_write_failed", extra={"id": doc_id, "error": str(e)})


async def _deliver(hit: dict[str, Any]) -> None:
    doc_id = hit["_id"]
    src = hit["_source"]
    # Version stamped by our own claim — every terminal write below is guarded
    # by it, so a sender that lost its lease cannot clobber the new owner.
    ver = {"seq_no": hit.get("_seq_no"), "primary_term": hit.get("_primary_term")}
    secret = secret_box.decrypt(src.get("secret_enc", ""))
    # 加密之前排队的那些投递文档里是明文 `webhook_url`，仍然认。
    url = secret_box.decrypt(src.get("webhook_url_enc", "")) or src.get("webhook_url") or ""
    try:
        # 渠道派发在 channels 那一张表里 —— 这里不知道有哪几个渠道，加一个渠道
        # 不需要回来改这个函数。
        await channels.send(
            src.get("channel"), {**src, "secret": secret, "webhook_url": url}, src["body"]
        )
        await _finish(doc_id, src, ok=True, **ver)
        logger.info("delivery_sent", extra={"id": doc_id, "channel": src.get("channel")})
    except ChannelError as e:
        # 四个渠道的失败共用一个基类：每加一个渠道就往 except 元组里塞一个类，
        # 是那种迟早会漏掉一个的写法。
        await _finish(doc_id, src, ok=False, error=_scrub(e), retryable=e.retryable, **ver)
        logger.warning("delivery_failed",
                       extra={"id": doc_id, "retryable": e.retryable, "error": _scrub(e)})
    except ApiError as e:
        # 渠道校验（webhook_url 不能为空、Slack 必须 https…）是配置错误，重试多少
        # 次都一样；之前当「未知异常」按 retryable 循环，每 30 s 一条带完整
        # traceback 的 ERROR。
        await _finish(doc_id, src, ok=False, error=_scrub(e), retryable=False, **ver)
        logger.warning("delivery_rejected",
                       extra={"id": doc_id, "channel": src.get("channel"), "error": _scrub(e)})
    except Exception as e:  # noqa: BLE001 — unexpected → retry
        await _finish(doc_id, src, ok=False, error=_scrub(e), retryable=True, **ver)
        logger.exception("delivery_error", extra={"id": doc_id})
    except BaseException:
        # Shutdown cancels this task mid-send. CancelledError is a
        # BaseException, so without this the job stayed `sending` and — before
        # the lease existed — was never retried. Release the claim so the next
        # tick picks it up promptly, then let the cancellation propagate.
        with contextlib.suppress(Exception):
            await _finish(doc_id, src, ok=False, error="gateway shutdown mid-send",
                          retryable=True, **ver)
        raise


async def tick() -> int:
    """One worker pass: claim + deliver all due jobs. Returns count delivered
    (attempted). Exposed for tests/manual runs."""
    delivered = 0
    for hit in await _due_jobs():
        if await _claim(hit):
            await _deliver(hit)
            delivered += 1
    return delivered


async def list_deliveries(kind: str | None = None, status: str | None = None,
                          ref: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    es = get_es()
    must: list[dict] = []
    if kind:
        must.append({"term": {"kind": kind}})
    if status:
        must.append({"term": {"status": status}})
    if ref:
        must.append({"term": {"ref": ref}})
    try:
        resp = await es.search(index=_index(), body={
            "size": max(1, min(limit, 200)),
            "query": {"bool": {"must": must or [{"match_all": {}}]}},
            "sort": [{"updated_at": {"order": "desc"}}],
            "_source": {"excludes": ["body", "secret_enc", "webhook_url_enc", "webhook_url"]},
        })
    except Exception:  # noqa: BLE001
        return []
    # id 要带出去：界面上的「重投」按它定位，_source 里没有。
    return [{**(h.get("_source") or {}), "id": h.get("_id")}
            for h in (resp.body.get("hits") or {}).get("hits") or []]


async def requeue(doc_id: str) -> bool:
    """把一条投递重新排进队列 —— 界面上「重投」按的就是它。

    死信是这个功能存在的理由：webhook 被撤销、SMTP 密码改了、群解散了，修好之后
    那几条已经躺进死信的报告不该只能靠客户自己去补。attempts 归零，退避重新起算。

    只接受终态（dead / failed / sent）。`queued` / `sending` 不动 —— 前者本来就在
    队里，后者正被某个 worker 持有，改它等于抢租约，会撞上 _finish 的 CAS。
    """
    es = get_es()
    try:
        cur = await es.get(index=_index(), id=doc_id)
    except Exception:  # noqa: BLE001
        return False
    src = cur.body.get("_source") or {}
    if src.get("status") in ("queued", "sending"):
        return False
    now = _now().isoformat()
    src.update({"status": "queued", "attempts": 0, "last_error": "",
                "next_attempt_at": now, "updated_at": now})
    try:
        await es.index(index=_index(), id=doc_id, document=src, refresh="wait_for",
                       if_seq_no=cur.body.get("_seq_no"),
                       if_primary_term=cur.body.get("_primary_term"))
    except Exception as e:  # noqa: BLE001
        logger.warning("requeue_failed", extra={"id": doc_id, "error": str(e)})
        return False
    logger.info("delivery_requeued", extra={"id": doc_id})
    return True


async def _loop() -> None:
    logger.info("notify_worker_started", extra={"interval_s": _interval()})
    while True:
        try:
            await tick()
            await asyncio.sleep(_interval())
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001
            logger.exception("notify_worker_loop_error")
            await asyncio.sleep(_interval())


def start() -> None:
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
