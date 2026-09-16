"""Audit log — best-effort write of every gateway action to a customer-side
ES index. Disabled by default (dev mode); customer admin opts in.

Why opt-in: enabling audit means the gateway's ES connection needs WRITE
permission on the audit index. Default-on would break the "gateway is read-only
on customer ES" guarantee.

Schema (one document per action):
    {
      "@timestamp": "2026-...",
      "action": "generate|execute|explain_log|investigate_alert|field_dict|kibana_link|feedback",
      "user": {"username": "...", "roles": [...]} | null,   ← from plugin proxy header
      "source_ip": "203.0.113.7" | absent,                  ← client IP (who/where)
      "index": "kibana_sample_data_logs",
      "license_status": "valid|expiring|...",
      "prompt_version": "v3-2026-04-30" | null,
      "duration_ms": 1234,
      "outcome": "success|fail",
      "error": "..."  (if outcome=fail),
      "extra": {...}   (action-specific fields, e.g. confidence / hits)
    }

The writer is a fire-and-forget asyncio task — never raises into the user's
request path. Audit failure is logged at WARN level only.
"""

import asyncio
import contextvars
import logging
import os
from datetime import datetime, timezone
from typing import Any

from .audit_sinks import Sink, load_sinks_from_env
from .es_client import get_es

logger = logging.getLogger("rst.audit")

DEFAULT_INDEX = ".rst_copilot_audit"

# Request source IP — set per-request by the gateway's outermost middleware and
# read by `write_event`. A ContextVar is task-safe: `asyncio.create_task` (used
# by `fire_and_forget`) copies the current context, so the audit task sees the
# IP of the request that scheduled it.
_request_ip: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "rst_audit_request_ip", default=None
)


def set_request_ip(ip: str | None) -> None:
    """Record the current request's client IP for inclusion in audit events."""
    _request_ip.set(ip or None)

# Lazily-initialized list of optional fan-out sinks (syslog/webhook).
# Built on first ``write_event`` call from env vars. ``reset_sinks()`` clears
# it so config reloads / tests can rebuild from a fresh env.
_sinks: list[Sink] | None = None


def _get_sinks() -> list[Sink]:
    global _sinks
    if _sinks is None:
        _sinks = load_sinks_from_env()
    return _sinks


def reset_sinks() -> None:
    """Clear the cached sink list so the next ``write_event`` rebuilds it.

    Used by tests and any future config-reload path.
    """
    global _sinks
    _sinks = None


def _enabled() -> bool:
    return os.environ.get("RST_AUDIT_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def _index_name() -> str:
    return os.environ.get("RST_AUDIT_INDEX", DEFAULT_INDEX).strip() or DEFAULT_INDEX


def _data_stream_mode() -> bool:
    """When ILM bootstrap is on, the audit index is a data stream (see ilm.py),
    which requires op_type=create on writes."""
    return os.environ.get("RST_ILM_BOOTSTRAP", "").strip().lower() in ("1", "true", "yes")


def is_enabled() -> bool:
    return _enabled()


def index_name() -> str:
    return _index_name()


async def write_event(
    action: str,
    *,
    index: str | None = None,
    user: dict[str, Any] | None = None,
    license_status: str | None = None,
    prompt_version: str | None = None,
    duration_ms: int | None = None,
    outcome: str = "success",
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Best-effort write. Never raises."""
    if not _enabled():
        return
    body: dict[str, Any] = {
        "@timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "outcome": outcome,
    }
    if index is not None:
        body["index"] = index
    if user is not None:
        body["user"] = user
    if license_status is not None:
        body["license_status"] = license_status
    if prompt_version is not None:
        body["prompt_version"] = prompt_version
    if duration_ms is not None:
        body["duration_ms"] = duration_ms
    if error is not None:
        body["error"] = error[:1000]
    if extra:
        body["extra"] = extra
    src_ip = _request_ip.get()
    if src_ip:
        body["source_ip"] = src_ip

    doc_id: str | None = None
    try:
        es = get_es()
        if _data_stream_mode():
            # Data streams are append-only and require op_type=create.
            resp = await es.index(index=_index_name(), document=body, op_type="create")
        else:
            resp = await es.index(index=_index_name(), document=body)
        doc_id = (resp or {}).get("_id") if hasattr(resp, "get") else None
    except Exception as e:  # noqa: BLE001
        logger.warning("audit_write_failed", extra={"action": action, "error": str(e)})

    # Fan-out to optional sinks (syslog / webhook). Each sink
    # already swallows its own errors; ``return_exceptions=True`` is belt-and-
    # braces so a sink that *does* raise can't leak into the caller.
    sinks = _get_sinks()
    if sinks:
        try:
            results = await asyncio.gather(
                *(s.write(body) for s in sinks),
                return_exceptions=True,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "audit_fanout_failed",
                extra={"action": action, "error": str(e)},
            )
        else:
            # 送不到的那些留个名字。ES 里那条记录才是本体，所以事件本身没丢 ——
            # 丢的是「转发到客户 SIEM」这一次投递，而如果没有任何痕迹，事后没人
            # 答得出「哪些没转出去」，也就无从重放。
            failed = [
                s.kind for s, ok in zip(sinks, results) if isinstance(ok, BaseException) or ok is False
            ]
            if failed:
                await _mark_forward_failed(doc_id, failed, action)


# Strong refs to in-flight audit tasks. asyncio keeps only a WEAK ref to a task,
# so without this a fire-and-forget write can be garbage-collected mid-flight
# and silently lost (see the CPython asyncio.create_task docs).
_pending_tasks: set[asyncio.Task] = set()


def fire_and_forget(coro: "asyncio.coroutines.Coroutine") -> None:
    """Schedule an audit write without awaiting. Use inside route handlers."""
    try:
        task = asyncio.create_task(coro)
    except RuntimeError:
        # No running loop (shouldn't happen in normal request handling).
        logger.warning("audit_no_running_loop")
        return
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


async def _mark_forward_failed(doc_id: str | None, kinds: list[str], action: str) -> None:
    """在审计记录上标出哪些转发目标没送到。

    只在**转发失败时**才多这一次 ES 写入，所以正常情况下审计的写入量不变。

    数据流模式下不做：data stream 是只追加的，update 会被 ES 拒绝。那种部署上
    这条信息只留在网关日志里 —— 不为了留痕去破坏 ILM 的前提。
    """
    logger.warning(
        "audit_forward_failed", extra={"action": action, "sinks": ",".join(kinds)}
    )
    if not doc_id or _data_stream_mode():
        return
    try:
        es = get_es()
        await es.update(index=_index_name(), id=doc_id, doc={"forward_failed": kinds})
    except Exception as e:  # noqa: BLE001
        # 标记本身失败无所谓：上面那行日志已经把同一件事说过了。
        logger.debug("audit_forward_mark_failed", extra={"error": str(e)})
