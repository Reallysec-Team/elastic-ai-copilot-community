"""License heartbeat scheduler — periodic phone-home to the license server.

The actual heartbeat protocol (HMAC-signed POST /v1/heartbeat, token refresh,
revocation surfacing, feature_keyring caching, next_heartbeat clamping) lives in
the shared SDK ``rstlic_lifecycle.LicenseLifecycle.heartbeat_if_due``, driven via
``license_state.perform_heartbeat``. This module is only the asyncio scheduler.

Cadence: every 24h on success, every 5min on failure (so a license-server
recovery — or a server-side revoke — is picked up promptly). The lifecycle's
``in_offline_grace`` is what eventually locks generative use after a sustained
outage; see ``license_state._compute_status``.
"""

import asyncio
import logging

from . import license_state as ls

logger = logging.getLogger("rst.heartbeat")

HEARTBEAT_INTERVAL_SECONDS = 24 * 3600
HEARTBEAT_RETRY_SECONDS = 5 * 60

_task: asyncio.Task | None = None


async def heartbeat_once() -> bool:
    """Run one heartbeat cycle. Returns True on success / not-due, False on a
    hard failure (revoked or transport error)."""
    ok = await ls.perform_heartbeat()
    if ok:
        logger.info("heartbeat_ok", extra={"license_id": ls.get_license_id()})
    elif ls.get_license_id() is None:
        # 没激活就没有心跳可打;每次启动一条 license_id=null error=null 的 WARNING
        # 只会让客户去查一个不存在的问题。
        logger.info("heartbeat_skipped_unactivated")
    else:
        logger.warning(
            "heartbeat_not_ok",
            extra={
                "license_id": ls.get_license_id(),
                "error": ls.get_state().get("last_heartbeat_error"),
            },
        )
    return ok


async def _loop() -> None:
    while True:
        try:
            ok = await heartbeat_once()
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS if ok else HEARTBEAT_RETRY_SECONDS)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("heartbeat_loop_error")
            await asyncio.sleep(HEARTBEAT_RETRY_SECONDS)


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
