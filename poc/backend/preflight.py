"""Production-readiness preflight checks.

Run once at startup and surfaced in /readyz. These catch the two silent
production failure modes:

  1. SSO disabled → per-user state (history / prefs / saved queries) and team
     triage sync collapse to the shared `_shared` / `_team` buckets, so there is
     no per-analyst isolation. Fine for a single-box demo; wrong for prod.
  2. 提示词里的时区没设 → 模型按 UTC 切日界，「今天下午」「昨天」「8月8号」这类
     问题查出来是空的或错的一天。现场真出过一次。
  3. The gateway's ES connection lacks write permission → audit logging drops
     events and server-side UI state silently falls back to localStorage, so an
     analyst's "已处置" mark never reaches the team. Better to surface it loudly.

Neither check is fatal — the gateway still starts. They warn + record state.
"""

from __future__ import annotations

import logging
import os

from . import user_state
from .auth import sso_enabled
from .es_client import get_es

logger = logging.getLogger("rst.preflight")

_results: dict[str, str] = {"sso": "unknown", "es_write": "unknown", "timezone": "unknown"}


def results() -> dict[str, str]:
    return dict(_results)


async def run() -> None:
    """Best-effort startup checks. Never raises."""
    # 1) SSO posture.
    if sso_enabled():
        _results["sso"] = "enabled"
    else:
        _results["sso"] = "disabled"
        # 1.1.19 起没有 SSO 也有独立用户表 + 三档角色,多用户不再依赖 SSO。
        # 老文案「there is NO per-analyst isolation … Enable SSO for any multi-user
        # deployment」已经不是真的,别再每次启动吓客户一次。
        if os.environ.get("RST_USER_DB_URL"):
            logger.info("sso_disabled — accounts come from the local user table (RST_USER_DB_URL).")
        else:
            logger.warning(
                "sso_disabled — RST_SSO_ENABLED is off and RST_USER_DB_URL is unset: only the "
                "single admin account exists and per-user state collapses to the shared bucket. "
                "Set RST_USER_DB_URL (bundled userdb) for multiple accounts, or enable SSO."
            )

    # 2) 提示词时区。默认 UTC —— 对 UTC+8 的客户，日界差 8 小时。
    tz = (os.environ.get("RST_TIMEZONE") or "").strip()
    _results["timezone"] = tz or "utc-default"
    if not tz:
        logger.warning(
            "timezone_unset — RST_TIMEZONE is not set, so the model reads 「今天」"
            "「昨天」「8月8号」against UTC. For a UTC+8 deployment every day-boundary "
            "question lands on the wrong day (or an empty range). Set RST_TIMEZONE=+08:00."
        )

    # 3) ES write permission (audit + user-state depend on it).
    status, err = await _probe_es_write()
    _results["es_write"] = status
    if status == "denied":
        logger.warning(
            "es_write_denied — the gateway's ES connection cannot write to "
            f"{user_state._index_name()} ({err}). Audit logging and server-side "
            "UI state (triage sync / history / prefs / saved queries) will NOT "
            "persist; the UI falls back to per-browser localStorage. Grant the ES "
            "user create/write on .rst_copilot_* for production."
        )


async def _probe_es_write() -> tuple[str, str | None]:
    """Write + delete a throwaway doc. Returns ('ok', None) or ('denied', err)."""
    idx = user_state._index_name()
    try:
        await user_state._ensure()
        es = get_es()
        await es.index(
            index=idx,
            id="_preflight_probe",
            document={"owner": "_preflight", "kind": "_probe", "key": "_probe", "value_json": "1"},
            refresh=False,
        )
        await es.delete(index=idx, id="_preflight_probe", refresh=False)
        return "ok", None
    except Exception as e:  # noqa: BLE001
        return "denied", str(e)


async def recheck_es_write() -> None:
    """Re-probe ES write only when it's not currently 'ok', so /readyz self-heals
    once ES recovers — without writing on every health check when already ok."""
    if _results.get("es_write") == "ok":
        return
    status, _ = await _probe_es_write()
    _results["es_write"] = status
