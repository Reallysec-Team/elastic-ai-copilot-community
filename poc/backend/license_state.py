"""License lifecycle state — RST license-server client built on the shared SDK.

Online-activation model (Recipe A — Python backend on the customer host):

  1. activate_from_text() — the operator pastes the license token. We verify it
     OFFLINE (RSA-PSS, via the shared ``rstlic_verifier``), then hand the
     license_id to the shared :class:`rstlic_lifecycle.LicenseLifecycle`, which
     POSTs /v1/activate. The server returns a refreshed license token, a
     hardware-fingerprint-bound session_token (SEC-AC-1), the heartbeat HMAC key
     (session_secret, SEC-HB-1), and — when the server has online keyring
     enabled — a ``feature_keyring`` for the entitled premium features
     (SEC-CC-1). The lifecycle persists all of it to RST_LICENSE_FILE.

  2. perform_heartbeat() (driven by heartbeat.py) — ``heartbeat_if_due`` sends a
     daily HMAC heartbeat that keeps the token fresh, refreshes the cached
     keyring, and surfaces server-side revocation. /v1/refresh-session rotates
     the session_token before its expiry.

  3. On every load we re-verify the session_token's embedded hardware
     fingerprint AND license_id against THIS host (SEC-AC-1): a license or
     activation record copied to another machine fails the check.

This module is intentionally a THIN product-specific layer over the SDK: the
activate / heartbeat_if_due / is_revoked / in_offline_grace policy lives in
``LicenseLifecycle`` (re-synced verbatim from the license-server repo); here we
only add the product's 7-state UI status, the unactivated-demo quota, and the
SEC-AC-1 session binding the SDK leaves to the product.

Status values (7-state model): unactivated / valid / expiring / grace /
expired / invalid / revoked / heartbeat_lost.
"""

import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import hmac

logger = logging.getLogger("rst.license_state")

from rstlic_verifier import (  # flat import — see backend/__init__.py
    InvalidLicense,
    LicenseError,
    LicenseVerifier,
    decode_payload,
    verify_session_token,
    verify_token,
)
from rstlic_storage import FileStorage
from rstlic_lifecycle import LicenseLifecycle, StorageKeys

LICENSE_FILE = Path(os.environ.get(
    "RST_LICENSE_FILE",
    str(Path(__file__).parent.parent / "license.json"),
))
PRODUCT_ID = "rst_elastic_ai_copilot"
APP_VERSION = os.environ.get("APP_VERSION", "1.1.0")
GRACE_PERIOD_DAYS = 7
# Default 5 is for "casual demo" UX. Active testing / dev environments should
# bump this via env (e.g. RST_TRIAL_DAILY_LIMIT=200).
try:
    TRIAL_DAILY_LIMIT = int(os.environ.get("RST_TRIAL_DAILY_LIMIT", "5"))
except ValueError:
    TRIAL_DAILY_LIMIT = 5

STATUS_UNACTIVATED = "unactivated"
STATUS_VALID = "valid"
STATUS_EXPIRING = "expiring"
STATUS_GRACE = "grace"
STATUS_EXPIRED = "expired"
STATUS_INVALID = "invalid"
STATUS_REVOKED = "revoked"
STATUS_HEARTBEAT_LOST = "heartbeat_lost"

_state: dict[str, Any] = {
    "status": STATUS_UNACTIVATED,
    "payload": None,
    "loaded_at": None,
    "last_heartbeat_ok_at": None,
    "last_heartbeat_attempt_at": None,
    "last_heartbeat_error": None,
    "load_error": None,
}
# The license_id currently installed (read out of the verified token), so the
# SDK's per-license_id-scoped is_revoked / in_offline_grace get the right key.
_license_id: Optional[str] = None
_lock = asyncio.Lock()

# One SDK lifecycle + storage instance for the process. The storage IS the
# persisted activation record now (RST_LICENSE_FILE as a k/v JSON owned by the
# SDK), replacing the bespoke record this module used to hand-roll.
_storage = FileStorage(str(LICENSE_FILE))
_keys = StorageKeys()
_life: Optional[LicenseLifecycle] = None

# Latest release the server offered on a heartbeat (P3). Download/staging is
# operator-triggered (not automatic), so we just stash what was advertised and
# let /api/admin/release/download act on it. None = no newer release offered.
_available_release: Optional[dict] = None


def _stash_available_release(release: dict) -> None:
    global _available_release
    _available_release = release


def get_available_release() -> Optional[dict]:
    """The release advertised by the most recent heartbeat, or None."""
    return _available_release


def report_release_verify_failed(reason: str, version: Optional[str] = None) -> None:
    """Best-effort §11 report to the license server when a release/content
    artifact fails signature/sha verification (intrusion signal). Never raises."""
    if not _license_id:
        return
    try:
        import requests
        requests.post(
            f"{_license_server_url()}/v1/release/verify-failed",
            json={"license_id": _license_id, "app_id": PRODUCT_ID,
                  "reason": (reason or "")[:500], "version": version or ""},
            timeout=10,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("release verify-failed report failed: %s", e)
_verifier_cache: Optional[LicenseVerifier] = None

# Storage key recording HOW this install was activated: "offline" for an
# air-gapped host-bound token (SEC-CC-1 keyring + bound_fingerprint baked into
# the signed payload, no /v1/activate, no heartbeat), anything else = online.
_MODE_KEY = "rstlic_mode"
_MODE_OFFLINE = "offline"

# Quota counts persist to disk so a uvicorn restart doesn't silently
# reset the daily trial cap.
_QUOTA_FILE = Path(os.environ.get(
    "RST_QUOTA_FILE",
    str(Path(__file__).parent.parent / "quota.json"),
))
_unactivated_calls: dict[str, int] = {}
_unactivated_lock = asyncio.Lock()


def _load_quota_from_disk() -> None:
    global _unactivated_calls
    try:
        if _QUOTA_FILE.exists():
            data = json.loads(_QUOTA_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _unactivated_calls = {
                    str(k): int(v) for k, v in data.items() if isinstance(v, (int, float))
                }
    except Exception:
        _unactivated_calls = {}


def _save_quota_to_disk() -> None:
    try:
        _QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _QUOTA_FILE.with_suffix(_QUOTA_FILE.suffix + ".tmp")
        tmp.write_text(json.dumps(_unactivated_calls), encoding="utf-8")
        os.replace(tmp, _QUOTA_FILE)
        try:
            os.chmod(_QUOTA_FILE, 0o600)
        except OSError:
            pass
    except Exception:
        pass  # best-effort; quota lives in-memory regardless


_load_quota_from_disk()


# ─────────────────────────────── public API ────────────────────────────────

async def initial_load() -> None:
    """Called from FastAPI lifespan startup."""
    await reload_license()


async def reload_license() -> None:
    """Re-read the activation record from disk, re-verify, recompute status."""
    async with _lock:
        _migrate_legacy_record_if_present()
        token = _get_life().get_token()
        if not token:
            _set_unactivated()
            return
        _verify_and_apply(token)


def _unwrap_token(text: str) -> str:
    """把用户贴进来的东西剥成裸 token。

    许可服务器发的离线 `.lic` 是一个 JSON 信封（fmt=rstlic-offline-bundle，token 在
    `token` 字段），在线证的邮件 / 控制台有时也是 `{"license_token": …}`。界面上传
    走前端 extractToken 已经会剥；这里让 API 也认，脚本 / headless 激活不用再拆一遍。
    不是 JSON 就原样返回。
    """
    t = (text or "").strip()
    if not t.startswith("{"):
        return t
    try:
        obj = json.loads(t)
    except ValueError:
        return t
    if not isinstance(obj, dict):
        return t
    for key in ("license_token", "license_key", "token"):
        v = obj.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return t


async def activate_from_text(license_text: str) -> dict[str, Any]:
    """Operator pastes the license token → verify offline → SDK /v1/activate →
    persist (SDK) → reload.

    Raises InvalidLicense (→ HTTP 400) with a clear message on every failure
    path: bad token, wrong product, no hardware fingerprint, server rejection,
    or server unreachable.
    """
    license_text = _unwrap_token(license_text)
    if not license_text:
        raise InvalidLicense("license 令牌为空")

    public_key_pem = _load_public_key()
    if not public_key_pem:
        raise InvalidLicense(
            "服务端未配置 license 公钥（设置 RST_LICENSE_PUBLIC_KEY 或 "
            "RST_LICENSE_PUBLIC_KEY_PATH）"
        )

    # Route by token type: an offline (air-gapped) token carries mode="offline"
    # + a baked-in host binding and is enforced entirely on the client; an
    # online token goes through /v1/activate. decode_payload here is for ROUTING
    # only — the chosen path re-verifies the signature.
    try:
        routing = decode_payload(license_text)
    except Exception:
        routing = {}
    if routing.get("mode") == _MODE_OFFLINE:
        return await _activate_offline(license_text, public_key_pem)

    # 1. Offline-verify the pasted token and pull out the license_id.
    payload = verify_token(license_text, public_key_pem)
    if payload.get("product") != PRODUCT_ID:
        raise InvalidLicense(f"license 属于其它产品：{payload.get('product')!r}")
    license_id = payload.get("license_id")
    if not license_id:
        raise InvalidLicense("license 令牌缺少 license_id")

    # 2. Hardware fingerprint (SEC-FP-1) — binds the activation to this host.
    #    Fail early with a clear message if no hardware identity is readable.
    from .server_guid import get_host_fingerprint
    from rstlic_client import RSTLicHardwareUnavailable
    try:
        fingerprint = get_host_fingerprint()
    except RSTLicHardwareUnavailable as e:
        raise InvalidLicense(f"无法读取本机硬件标识，无法激活：{e}")

    # mark this install as online (clears any prior offline marker).
    _storage.set(_MODE_KEY, "")

    # 3. Online activation — delegated to the shared lifecycle. It POSTs
    #    /v1/activate and persists token + session_token + session_secret +
    #    feature_keyring. activate() is best-effort (never raises) so a
    #    server outage can't crash the app; for the operator-driven flow we
    #    surface the outcome explicitly below.
    life = _get_life()
    await asyncio.to_thread(life.activate, license_id=license_id)

    if life.is_revoked(license_id):
        raise InvalidLicense("该 license 已被吊销（license server 拒绝激活）")
    session_token = life.get_session_token()
    if not session_token:
        # 服务器明确拒了（台数用完、license 不属于这个产品…）和根本没连上是两回事：
        # 前者让客户去查网络只会白忙。把服务器给的原因原样带出来。
        why = getattr(life, "last_activate_error", None)
        if getattr(life, "last_activate_rejected", False):
            raise InvalidLicense(f"license 服务器拒绝了这次激活：{why}。请联系销售。")
        raise InvalidLicense(
            "激活未完成：无法连接 license 服务器"
            + (f"（{why}）" if why else "")
            + "。请检查到 license server 的网络后重试，或联系销售。"
        )

    # 4. SEC-AC-1: the returned session_token must bind to THIS host AND this
    #    license_id (a trial's session token must not vouch for an enterprise
    #    license pasted on the same machine).
    verify_session_token(session_token, public_key_pem, fingerprint,
                          expected_license_id=license_id)

    await reload_license()
    return get_state()


async def _activate_offline(license_text: str, public_key_pem: bytes) -> dict[str, Any]:
    """Offline / air-gapped activation: no /v1/activate, no session token, no
    heartbeat. The host binding (``bound_fingerprint``) and the SEC-CC-1
    ``feature_keyring`` are baked into the signed payload; we verify the
    signature, enforce the host binding (constant-time), and persist locally.
    """
    from .server_guid import get_host_fingerprint
    from rstlic_client import RSTLicHardwareUnavailable
    try:
        fingerprint = get_host_fingerprint()
    except RSTLicHardwareUnavailable as e:
        raise InvalidLicense(f"无法读取本机硬件标识，无法激活：{e}")

    # validate_offline does signature + schema + expiry + product + CRL, then a
    # constant-time compare of the token's bound_fingerprint to THIS host. A
    # token minted for another machine is rejected here (the copied-file attack).
    try:
        payload = _verifier(public_key_pem).validate_offline(
            license_text, host_fingerprint=fingerprint, expected_product=PRODUCT_ID,
        )
    except LicenseError as e:
        raise InvalidLicense(f"离线 license 校验失败：{e}")

    license_id = payload.get("license_id")
    if not license_id:
        raise InvalidLicense("license 令牌缺少 license_id")

    # Persist: the token itself + the embedded SEC-CC-1 keyring + contact-state
    # markers. Clear any online session material from a prior activation so the
    # load path takes the offline branch.
    _storage.set(_keys.token, license_text)
    _storage.set(_MODE_KEY, _MODE_OFFLINE)
    _storage.set(_keys.state_lid, license_id)
    _storage.set(_keys.revoked, "")
    _storage.set(_keys.session_token, "")
    _storage.set(_keys.session_secret, "")
    keyring = payload.get("feature_keyring")
    if isinstance(keyring, dict):
        _storage.set(_keys.feature_keyring, json.dumps(keyring))

    from feature_unlock import reset_cache
    reset_cache()
    await reload_license()
    return get_state()


async def deactivate() -> dict[str, Any]:
    """Clear the local activation record → revert to unactivated / demo mode.

    Wipes the stored license token plus all online session material (session
    token/secret, heartbeat markers) and the cached SEC-CC-1 feature keyring,
    then recomputes state. This is a LOCAL operator action performed on THIS
    host: it does not notify the license server, so the license_id itself stays
    valid and can be re-activated later (here or, within its node cap, on
    another host). The unactivated-demo trial quota is intentionally left
    untouched.
    """
    async with _lock:
        for k in (
            _keys.token, _keys.session_token, _keys.session_secret,
            _keys.feature_keyring, _keys.state_lid, _keys.revoked,
            _keys.last_ok, _keys.next_hb,
        ):
            _storage.set(k, "")
        _storage.set(_MODE_KEY, "")
    try:
        from feature_unlock import reset_cache
        reset_cache()
    except Exception:
        pass  # cache reset is best-effort; reload recomputes entitlements anyway
    await reload_license()
    return get_state()


def get_state() -> dict[str, Any]:
    p = _state.get("payload") or {}
    return {
        "status": _state["status"],
        "license_id": p.get("license_id"),
        "license_type": p.get("license_type"),
        "email": p.get("email"),
        "issue_date": p.get("issue_date"),
        "expiry_date": p.get("expiry_date"),
        "max_nodes": p.get("max_nodes"),
        "features": list(p.get("features") or []),
        "product": p.get("product"),
        "loaded_at": _state.get("loaded_at"),
        "last_heartbeat_ok_at": _state.get("last_heartbeat_ok_at"),
        "last_heartbeat_attempt_at": _state.get("last_heartbeat_attempt_at"),
        "last_heartbeat_error": _state.get("last_heartbeat_error"),
        "load_error": _state.get("load_error"),
    }


def has_feature(feature: str) -> bool:
    p = _state.get("payload")
    if not p:
        return False
    feats = p.get("features") or []
    # "*" is the enterprise wildcard — license-server issues it for unlimited
    # licenses, and treating it as a literal feature id (the prior bug) caused
    # every paid endpoint to 403 under an enterprise license.
    if "*" in feats:
        return True
    return feature in feats


def feature_allowed(feature: str) -> bool:
    """Feature is allowed if the license has it OR we're in unactivated demo mode.

    Unactivated mode quota is enforced separately by the license gate; here we
    just let the feature itself be exercised so trials and demos can show its
    UX. Lives here rather than in main.py so a router module can gate itself
    without importing the app (main.py keeps a thin alias for its own use).
    """
    if get_state()["status"] == STATUS_UNACTIVATED:
        return True
    return has_feature(feature)


def get_license_id() -> Optional[str]:
    """The license_id of the currently-loaded license, or None when unactivated.

    SEC-CC-1 feature unlocking needs this (with the host fingerprint) to derive
    the per-feature wrap key.
    """
    return _license_id


def get_feature_keyring() -> Optional[dict]:
    """The SEC-CC-1 feature keyring (``{feature: wrapped_b64}``) or None.

    Same storage key for both activation modes, so consumers (``feature_unlock``)
    are mode-agnostic: online installs cache it from the activate/heartbeat
    response; offline installs persist the keyring baked into the signed token at
    activation time."""
    return _get_life().get_feature_keyring()


def is_offline() -> bool:
    """True when this install was activated with an air-gapped offline token."""
    return _storage.get(_MODE_KEY) == _MODE_OFFLINE


# -- heartbeat (driven by heartbeat.py) --------------------------------------

async def perform_heartbeat() -> bool:
    """Run one heartbeat cycle via the shared lifecycle, then recompute status.

    Returns True when there is an active license to heartbeat and the cycle
    did not surface a hard failure (revoked / transport error). Best-effort:
    transport errors are absorbed by the lifecycle and reflected via
    in_offline_grace on the next status recompute.
    """
    if not _license_id:
        return False  # unactivated — nothing to heartbeat
    if is_offline():
        return True  # air-gapped: no phone-home; sleep the full interval
    life = _get_life()
    metrics = await _heartbeat_metrics()
    self_attempt = _iso_now()

    # P1 online update: tell the server which content pack we hold (etag) and
    # apply any fresher one it inlines. Fail-closed — a bad/rollback pack raises
    # inside apply(), which heartbeat_if_due swallows, so we keep the current
    # pack (or the built-in defaults) and the heartbeat still succeeds.
    # Relative, NOT flat: content_store is product code and itself uses
    # relative imports (`from .rstlic_verifier import ...`). The flat form
    # loaded it as a top-level module with no parent package and that import
    # blew up — every heartbeat on every activated online install had failed
    # with ImportError since 2026-07-11 (revocation and keyring refresh never
    # reached customers). Only the vendored rstlic_* SDK is imported flat.
    from . import content_store

    def _on_content_pack(pack: dict) -> None:
        token = pack.get("token")
        if token:
            content_store.apply(token, actor="online", source="online")

    try:
        await asyncio.to_thread(
            life.heartbeat_if_due, license_id=_license_id, metrics=metrics,
            content_sha_provider=content_store.active_sha,
            on_content_pack=_on_content_pack,
            on_release=_stash_available_release,
        )
        await asyncio.to_thread(_refresh_session_if_due, life)
        ok = not life.is_revoked(_license_id)
        async with _lock:
            _state["last_heartbeat_attempt_at"] = self_attempt
            _state["last_heartbeat_error"] = None if ok else "license revoked by server"
            token = life.get_token()
            if token:
                _verify_and_apply(token)
        return ok
    except Exception as e:  # pragma: no cover — defensive; lifecycle absorbs most
        async with _lock:
            _state["last_heartbeat_attempt_at"] = self_attempt
            _state["last_heartbeat_error"] = f"{type(e).__name__}: {e}"
        return False


# -- quota (unactivated demo mode) -------------------------------------------

def _quota_day() -> str:
    """额度按哪一天算 —— 部署所在时区的日期，不是 UTC 的。

    界面上写的是「每天 N 次」。按 UTC 切日的话，UTC+8 的客户额度在早上八点重置，
    那不是他们的每天。升级之后第一次跨越旧键会重新计数一次（多给一天的额度），
    只影响未激活试用，不再另做迁移。
    """
    from . import settings as gw_settings

    return datetime.now(gw_settings.product_tz()).date().isoformat()


async def consume_unactivated_quota() -> bool:
    """Allow N /api/generate calls per day in unactivated mode."""
    today = _quota_day()
    async with _unactivated_lock:
        for k in list(_unactivated_calls.keys()):
            if k != today:
                del _unactivated_calls[k]
        count = _unactivated_calls.get(today, 0)
        if count >= TRIAL_DAILY_LIMIT:
            _save_quota_to_disk()
            return False
        _unactivated_calls[today] = count + 1
        _save_quota_to_disk()
        return True


async def refund_unactivated_quota() -> None:
    """Reverse a consume — used when the actual LLM call failed."""
    today = _quota_day()
    async with _unactivated_lock:
        count = _unactivated_calls.get(today, 0)
        if count > 0:
            _unactivated_calls[today] = count - 1
            _save_quota_to_disk()


# ─────────────────────────────── internals ─────────────────────────────────

def _verifier(public_key_pem: bytes) -> LicenseVerifier:
    """A LicenseVerifier bound to this product + public key, for the offline
    path (validate_offline). Cached after first build."""
    global _verifier_cache
    if _verifier_cache is None:
        _verifier_cache = LicenseVerifier(
            public_key_pem=public_key_pem, expected_product=PRODUCT_ID,
        )
    return _verifier_cache


def _get_life() -> LicenseLifecycle:
    global _life
    if _life is None:
        from .server_guid import get_server_guid
        from rstlic_client import RSTLicClient
        client = RSTLicClient(
            license_server_url=_license_server_url(),
            app_id=PRODUCT_ID,
            app_version=APP_VERSION,
            server_guid=get_server_guid(),
        )
        _life = LicenseLifecycle(
            client=client,
            storage=_storage,
            offline_grace_days=GRACE_PERIOD_DAYS,
            keys=_keys,
        )
    return _life


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _license_server_url() -> str:
    # Production default — the rst-platform license server. Override with the
    # LICENSE_SERVER_URL env var for local / staging license servers.
    return (
        os.environ.get("LICENSE_SERVER_URL", "").strip()
        or "https://license.reallysec.com"
    ).rstrip("/")


def _set_unactivated() -> None:
    global _license_id
    _license_id = None
    _state["status"] = STATUS_UNACTIVATED
    _state["payload"] = None
    _state["loaded_at"] = None
    _state["load_error"] = None


def _set_invalid(reason: str) -> None:
    global _license_id
    _license_id = None
    _state["status"] = STATUS_INVALID
    _state["payload"] = None
    _state["load_error"] = reason


def _verify_and_apply(token: str) -> None:
    """Verify the cached license token + session token, recompute status.

    Must be called with ``_lock`` held (reload_license / perform_heartbeat do).
    """
    global _license_id
    public_key_pem = _load_public_key()
    if not public_key_pem:
        _set_invalid("服务端未配置 license 公钥")
        return

    # 1. License token signature + product.
    try:
        payload = verify_token(token, public_key_pem)
    except InvalidLicense as e:
        _set_invalid(str(e))
        return
    if payload.get("product") != PRODUCT_ID:
        _set_invalid(f"license 属于其它产品：{payload.get('product')!r}")
        return
    license_id = payload.get("license_id") or ""

    # 2. Host binding. Offline tokens carry it in the signed payload
    #    (bound_fingerprint); online tokens enforce it via the SEC-AC-1 session
    #    token. Either way, a license/record copied to another machine is
    #    rejected. (Expiry → status below, so grace/expired still surface;
    #    signature already checked above.)
    from .server_guid import get_host_fingerprint
    from rstlic_client import RSTLicHardwareUnavailable
    try:
        fingerprint = get_host_fingerprint()
    except RSTLicHardwareUnavailable as e:
        _set_invalid(f"无法读取本机硬件标识：{e}")
        return

    if is_offline():
        bound = payload.get("bound_fingerprint")
        if payload.get("mode") != _MODE_OFFLINE or not isinstance(bound, str) or not bound:
            _set_invalid("离线 license 缺少主机绑定 (bound_fingerprint)")
            return
        if not hmac.compare_digest(bound.strip().lower(), fingerprint.strip().lower()):
            _set_invalid("离线 license 绑定到其它主机，本机无法使用")
            return
    else:
        session_token = _get_life().get_session_token()
        try:
            verify_session_token(session_token, public_key_pem, fingerprint,
                                 expected_license_id=license_id or None)
        except InvalidLicense as e:
            _set_invalid(str(e))
            return

    _license_id = license_id or None
    _state["payload"] = payload
    _state["loaded_at"] = _iso_now()
    _state["load_error"] = None
    _state["last_heartbeat_ok_at"] = _storage.get(_keys.last_ok) or None
    _state["status"] = _compute_status(payload)


def _compute_status(payload: dict[str, Any]) -> str:
    """Map the verified payload + SDK revoke/grace signals to the 7-state UI."""
    life = _get_life()
    lid = payload.get("license_id") or None

    # Remote revocation (heartbeat / CRL) wins outright — fail closed.
    if life.is_revoked(lid):
        return STATUS_REVOKED

    expiry_str = payload.get("expiry_date")
    if not expiry_str:
        return STATUS_INVALID
    try:
        expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
    except ValueError:
        return STATUS_INVALID
    now = datetime.now(timezone.utc)
    delta_days = (expiry - now).total_seconds() / 86400

    # Online installs only: server contact lost beyond the offline grace window
    # → lock generative use (only meaningful while the license is still valid).
    # Air-gapped offline installs never phone home, so their bound is expiry,
    # not contact — skip the heartbeat-lost check entirely.
    if not is_offline() and delta_days >= 0 and not life.in_offline_grace(lid):
        return STATUS_HEARTBEAT_LOST

    if delta_days >= GRACE_PERIOD_DAYS:
        return STATUS_VALID
    if delta_days >= 0:
        return STATUS_EXPIRING
    if delta_days >= -GRACE_PERIOD_DAYS:
        return STATUS_GRACE
    return STATUS_EXPIRED


def _refresh_session_if_due(life: LicenseLifecycle) -> None:
    """Rotate the SEC-AC-1 session token when it is within 7 days of expiry.

    Reads the expiry from the cached session token itself (no separate
    persisted field needed), then persists any rotated token via the client +
    storage. Best-effort — the next heartbeat retries.
    """
    from rstlic_verifier import decode_payload, session_token_expiry
    from datetime import timedelta
    session_token = life.get_session_token()
    if not session_token or not _license_id:
        return
    try:
        exp = session_token_expiry(decode_payload(session_token))
    except Exception:
        return
    if exp is None:
        return
    if exp - datetime.now(timezone.utc) > timedelta(days=7):
        return
    from .server_guid import get_host_fingerprint
    try:
        fp = get_host_fingerprint()
        r = life._client.refresh_session(license_id=_license_id, host_fingerprint=fp)  # noqa: SLF001
    except Exception:
        return
    new_sess = r.get("session_token") if isinstance(r, dict) else None
    if new_sess:
        _storage.set(_keys.session_token, new_sess)


async def _heartbeat_metrics() -> dict[str, Any]:
    """ES cluster identity — abuse-detection metadata only, never identity."""
    try:
        from .server_guid import get_cluster_metadata
        cluster_meta = await get_cluster_metadata()
    except Exception:
        cluster_meta = {}
    return {
        "cluster_uuid": cluster_meta.get("cluster_uuid"),
        "cluster_name": cluster_meta.get("cluster_name"),
        "es_version": cluster_meta.get("es_version"),
        "ts": _iso_now(),
    }


def _migrate_legacy_record_if_present() -> None:
    """One-shot upgrade: map a pre-SDK activation record into the SDK k/v store.

    The previous license_state wrote RST_LICENSE_FILE as a bespoke record
    (``license_token`` / ``session_token`` / ``session_secret`` / ...). The SDK
    FileStorage reads that file as a flat k/v map; those legacy keys don't match
    StorageKeys, so without migration an upgraded install would look unactivated
    and force a re-activation. Map them once so existing activations survive.
    """
    # If the SDK token key is already populated, there is nothing to migrate.
    if _storage.get(_keys.token):
        return
    legacy_token = _storage.get("license_token")
    if not legacy_token:
        return
    _storage.set(_keys.token, legacy_token)
    sess = _storage.get("session_token")
    if sess:
        _storage.set(_keys.session_token, sess)
    secret = _storage.get("session_secret")
    if secret:
        _storage.set(_keys.session_secret, secret)
    lid = _storage.get("license_id")
    if lid:
        # Seed the per-license_id contact-state key + a last_ok so the migrated
        # install starts inside its offline-grace window (it had been
        # heartbeating before the upgrade).
        _storage.set(_keys.state_lid, lid)
        if not _storage.get(_keys.last_ok):
            _storage.set(_keys.last_ok, _iso_now())


def _load_public_key() -> Optional[bytes]:
    raw = os.environ.get("RST_LICENSE_PUBLIC_KEY")
    if raw:
        if raw.startswith("-----"):
            return raw.encode("utf-8")
        try:
            return base64.b64decode(raw)
        except Exception:
            return None
    pem_path = os.environ.get(
        "RST_LICENSE_PUBLIC_KEY_PATH",
        str(Path(__file__).parent.parent / "keys" / "license_public.pem"),
    )
    p = Path(pem_path)
    if p.exists():
        try:
            return p.read_bytes()
        except OSError:
            return None
    return None
