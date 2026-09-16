"""rstlic_lifecycle — platform-agnostic activate / heartbeat / grace orchestration.

This is the de-Splunk-ified core of the old ``mcp_license_phone_home`` module.
It wires :class:`rstlic_client.RSTLicClient` (transport) to a
:mod:`rstlic_storage` backend (persistence) and owns the lifecycle policy:

  * activate once after the entitlement is locally accepted,
  * heartbeat on a server-driven cadence (clamped against a hostile server),
  * expose ``is_revoked`` / ``in_offline_grace`` so the caller can gate
    functionality when the server has pulled the license or gone dark.

NOTHING in here imports Splunk. A Splunk app uses it via a thin adapter
(``mcp_license_phone_home``) that supplies a ``CallableStorage`` over
``storage/passwords``; a plain backend uses ``FileStorage``; a test uses
``MemoryStorage``.

Usage (non-Splunk product)::

    from rstlic_client import RSTLicClient
    from rstlic_storage import FileStorage
    from rstlic_lifecycle import LicenseLifecycle

    client = RSTLicClient(
        license_server_url='https://license.reallysec.com',
        app_id='my-product',
        app_version='1.0.0',
        server_guid=stable_host_id,        # any stable per-host string
    )
    life = LicenseLifecycle(
        client=client,
        storage=FileStorage('/var/lib/my-product/license.json'),
        offline_grace_days=3,
    )

    life.activate(license_id='LIC-...')           # once, after local verify
    token = life.heartbeat_if_due(license_id='LIC-...', metrics={'qpd': 12})
    if life.is_revoked('LIC-...') or not life.in_offline_grace('LIC-...'):
        ...  # degrade to read-only
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from rstlic_client import (
    RSTLicClient, RSTLicRevoked, RSTLicRejected, RSTLicUnavailable,
    RSTLicHardwareUnavailable,
)
from rstlic_storage import Storage

logger = logging.getLogger('rstlic_lifecycle')

DEFAULT_OFFLINE_GRACE_DAYS = 3

# Cap on how far into the future we trust the server's ``next_heartbeat_at``.
# The heartbeat is the channel through which remote revoke takes effect, so a
# compromised / MITM'd server that sets next_heartbeat to "year 9999" would
# otherwise suppress revocation forever. 48h gives room for legitimate retries
# while keeping the worst-case revoke latency bounded.
_MAX_NEXT_HEARTBEAT_SKEW_SECONDS = 2 * 24 * 60 * 60


@dataclass(frozen=True)
class StorageKeys:
    """The storage key names the lifecycle reads/writes.

    Defaults are generic. The Splunk adapter overrides every field with the
    legacy ``mcp_license_*`` names so existing installs keep finding their
    already-persisted credentials — DO NOT change those legacy values.
    """
    token:          str = 'rstlic_token'
    next_hb:        str = 'rstlic_next_hb'
    last_ok:        str = 'rstlic_last_ok'
    revoked:        str = 'rstlic_revoked'
    session_secret: str = 'rstlic_session_secret'
    session_token:  str = 'rstlic_session_token'
    # V2: the license_id the cached contact-state above belongs to. Lets the
    # grace / revoked checks ignore state left by a DIFFERENT license — see
    # is_revoked / in_offline_grace.
    state_lid:      str = 'rstlic_state_lid'
    # SEC-CC-1: the online feature_keyring delivered by activate/heartbeat,
    # cached (JSON) so a product can unlock sealed features after a restart
    # without an immediate re-activation round trip.
    feature_keyring: str = 'rstlic_feature_keyring'


# ---------------------------------------------------------------------------
# Time helpers (moved verbatim from mcp_license_phone_home so behaviour is
# byte-for-byte identical for the Splunk adapter).
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _parse_iso(s: str) -> datetime:
    """Parse an ISO-8601 timestamp into a tz-aware UTC datetime.

    Handles every shape the cache actually sees: Pydantic timestamps with
    microseconds + literal Z, explicit +00:00 offsets, and the SDK's own
    no-microsecond Z form. (Python 3.7+ fromisoformat handles the rest once
    the trailing Z is normalised.)
    """
    s = s.strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    return datetime.fromisoformat(s)


def _decode_token_payload(token: str) -> Optional[dict]:
    """Decode (WITHOUT verifying) the JSON payload of a license token.

    Used only to read advisory fields the server embedded for the SDK
    (``offline_grace_days`` etc.). No signature check is done here — and the
    caller must therefore only ever use the result to TIGHTEN policy, never
    loosen it (see ``_effective_grace_days``). Kept crypto-free on purpose so
    a heartbeat-only deployment doesn't have to pull in ``cryptography``.
    """
    if not token or '.' not in token:
        return None
    try:
        payload_b64 = token.split('.', 1)[0]
        payload = json.loads(base64.b64decode(payload_b64).decode('utf-8'))
        return payload if isinstance(payload, dict) else None
    except Exception:  # noqa: BLE001 — any decode failure → no embedded policy
        return None


def _clamp_next_heartbeat(server_value: str) -> str:
    """Cap the server-supplied next_heartbeat_at at now + max skew.

    Returns a normalized ISO string. Unparseable input → clamped value so a
    malformed response from a compromised server cannot suppress heartbeats
    (and thus revocation) indefinitely.
    """
    upper = datetime.now(timezone.utc) + timedelta(seconds=_MAX_NEXT_HEARTBEAT_SKEW_SECONDS)
    try:
        proposed = _parse_iso(server_value)
    except (ValueError, TypeError):
        proposed = upper
    if proposed > upper:
        proposed = upper
    return proposed.strftime('%Y-%m-%dT%H:%M:%SZ')


class LicenseLifecycle:
    """Owns activate / heartbeat / grace policy for one (client, storage) pair.

    Parameters
    ----------
    client:
        A configured :class:`rstlic_client.RSTLicClient` (carries app_id,
        app_version, server_guid, server URL). OPTIONAL: the read-only status
        methods only read storage, so a caller that just needs to gate on
        cached state can construct with client=None.
    storage:
        Any :mod:`rstlic_storage` backend (get/set of str).
    offline_grace_days:
        How many days past the last successful contact the product should keep
        working when the license server is unreachable. Mirrors the server's
        ``LICENSE_OFFLINE_GRACE_DAYS``.
    keys:
        Storage key names. Leave default for new products; the Splunk adapter
        passes legacy names.
    """

    def __init__(self, *,
                 client: Optional[RSTLicClient] = None,
                 storage: Storage,
                 offline_grace_days: int = DEFAULT_OFFLINE_GRACE_DAYS,
                 keys: Optional[StorageKeys] = None):
        self._client = client
        self._store = storage
        self._grace_days = int(offline_grace_days)
        self._keys = keys or StorageKeys()

    # -- fingerprint -------------------------------------------------------
    def _fingerprint(self) -> Optional[str]:
        """Compute this host's hardware fingerprint, or None on hard-fail.

        SEC-FP-1: returns None (and logs) rather than falling back to a
        guessable public-input hash when no hardware identifier is readable.
        Callers treat None as "cannot activate/heartbeat this cycle".
        """
        if self._client is None:
            logger.warning('lifecycle has no client; cannot phone home this cycle')
            return None
        try:
            return self._client.fingerprint(self._client.server_guid, self._client.app_id)
        except RSTLicHardwareUnavailable as e:
            logger.error('fingerprint failed (no hardware identifier): %s', e)
            return None

    # -- activate ----------------------------------------------------------
    def activate(self, *, license_id: str, splunk_version: str = '') -> None:
        """Phone home to bind this host to the license. Best-effort: failures
        are logged, never raised — the caller already locally verified the
        entitlement, so a license-server outage at activate time must not
        block the customer.
        """
        if not license_id:
            logger.warning('activate: missing license_id; skipping')
            return
        fp = self._fingerprint()
        if fp is None:
            return

        # Remembered so the operator-facing flow can say *why* (rejected vs
        # unreachable) instead of one blended "couldn't connect or was rejected".
        self.last_activate_error = None
        self.last_activate_rejected = False
        try:
            resp = self._client.activate(license_id=license_id, host_fingerprint=fp,
                                         splunk_version=splunk_version)
        except RSTLicRevoked:
            self._store.set(self._keys.revoked, '1')
            self._store.set(self._keys.state_lid, license_id)
            logger.warning('activate: server reports license %s revoked', license_id)
            return
        except RSTLicRejected as e:
            self.last_activate_error = str(e)
            self.last_activate_rejected = True
            logger.error('activate rejected for %s: %s', license_id, e)
            return
        except RSTLicUnavailable as e:
            self.last_activate_error = str(e)
            logger.info('activate unavailable (will retry via heartbeat): %s', e)
            return

        self._persist_contact(resp, include_session=True, license_id=license_id)

    # -- heartbeat ---------------------------------------------------------
    def heartbeat_if_due(self, *, license_id: str,
                         metrics: Optional[dict] = None,
                         content_sha_provider: Optional[Callable[[], Optional[str]]] = None,
                         on_content_pack: Optional[Callable[[dict], None]] = None,
                         on_release: Optional[Callable[[dict], None]] = None) -> str:
        """If the cached next_heartbeat_at has arrived, post an HMAC-signed
        heartbeat and update the cached token. Returns the (possibly refreshed)
        token, or the existing cached token when not due / on transient error.

        P1 online update (optional, product-supplied, kept generic here):
          * ``content_sha_provider`` returns the sha256 of the content pack the
            product currently holds, so the server can skip re-sending it.
          * ``on_content_pack`` is invoked with the server's inlined pack dict
            (``{token, sha256, version}``) when one is returned. The product
            verifies + applies it fail-closed; any exception it raises is
            swallowed here so a bad pack can never break the heartbeat.
          * ``on_release`` is invoked with the server's ``release`` dict
            (``{version, manifest_url, artifacts}``) when a newer release is
            offered, so the product can surface it for an operator-triggered
            download. Exceptions are swallowed too.
        """
        if not license_id:
            return self._store.get(self._keys.token)

        next_hb_str = self._store.get(self._keys.next_hb)
        if next_hb_str:
            try:
                if datetime.now(timezone.utc) < _parse_iso(next_hb_str):
                    return self._store.get(self._keys.token)
            except ValueError:
                pass  # malformed cache — treat as due

        fp = self._fingerprint()
        if fp is None:
            return self._store.get(self._keys.token)

        session_secret = self._store.get(self._keys.session_secret)
        if not session_secret:
            logger.warning('heartbeat: no cached session_secret; re-activate to mint one (SEC-HB-1)')
            return self._store.get(self._keys.token)

        content_sha = None
        if content_sha_provider is not None:
            try:
                content_sha = content_sha_provider()
            except Exception as e:  # noqa: BLE001 — never fail a heartbeat computing the etag
                logger.info('content_sha provider failed (sending full pack): %s', e)

        try:
            resp = self._client.heartbeat(license_id=license_id, host_fingerprint=fp,
                                          session_secret=session_secret, metrics=metrics or {},
                                          content_sha=content_sha)
        except RSTLicRevoked:
            self._store.set(self._keys.revoked, '1')
            self._store.set(self._keys.state_lid, license_id)
            logger.warning('heartbeat: server reports license %s revoked', license_id)
            return self._store.get(self._keys.token)
        except RSTLicRejected as e:
            logger.error('heartbeat rejected: %s', e)
            return self._store.get(self._keys.token)
        except RSTLicUnavailable as e:
            logger.info('heartbeat unavailable (will retry next tick): %s', e)
            return self._store.get(self._keys.token)

        if resp.get('revoked'):
            self._store.set(self._keys.revoked, '1')
            self._store.set(self._keys.state_lid, license_id)
        self._persist_contact(resp, include_session=False, license_id=license_id)
        pack = resp.get('content_pack')
        if pack and on_content_pack is not None:
            try:
                on_content_pack(pack)
            except Exception as e:  # noqa: BLE001 — pack apply must never break the heartbeat
                logger.warning('online content pack apply failed (keeping current): %s', e)
        rel = resp.get('release')
        if rel and on_release is not None:
            try:
                on_release(rel)
            except Exception as e:  # noqa: BLE001 — surfacing a release must never break the heartbeat
                logger.warning('release surface hook failed: %s', e)
        return self._store.get(self._keys.token)

    # -- shared persistence ------------------------------------------------
    def _persist_contact(self, resp: dict[str, Any], *, include_session: bool,
                         license_id: str = '') -> None:
        token = resp.get('token') or ''
        if token:
            self._store.set(self._keys.token, token)
        next_hb = resp.get('next_heartbeat_at') or ''
        if next_hb:
            self._store.set(self._keys.next_hb, _clamp_next_heartbeat(str(next_hb)))
        self._store.set(self._keys.last_ok, _now_iso())
        # V2: stamp WHICH license this successful contact was for, so a later
        # check against a different installed license can tell the cached
        # last_ok / revoked state is "foreign" and not grant it grace.
        if license_id:
            self._store.set(self._keys.state_lid, license_id)
        # SEC-CC-1: cache the online feature_keyring (activate AND heartbeat
        # carry it). Only overwrite when present so a response that omits it
        # (online keyring disabled) leaves the last-good cached copy intact.
        keyring = resp.get('feature_keyring')
        if isinstance(keyring, dict):
            try:
                self._store.set(self._keys.feature_keyring, json.dumps(keyring))
            except Exception as e:  # noqa: BLE001 — never fail a contact on cache write
                logger.info('feature_keyring cache write skipped: %s', e)
        if include_session:
            # Only /v1/activate (and /refresh-session) return these.
            self._store.set(self._keys.revoked, '')  # clear any stale flag
            secret = resp.get('session_secret') or ''
            if secret:
                self._store.set(self._keys.session_secret, secret)
            sess_token = resp.get('session_token') or ''
            if sess_token:
                self._store.set(self._keys.session_token, sess_token)

    # -- read-only status --------------------------------------------------
    def get_token(self) -> str:
        return self._store.get(self._keys.token)

    def get_session_token(self) -> str:
        return self._store.get(self._keys.session_token)

    def get_feature_keyring(self) -> Optional[dict]:
        """The cached SEC-CC-1 feature keyring (``{feature: wrapped_b64}``), or
        None. Pass it to ``rstlic_features.unlock_data_key`` to unlock sealed
        premium features. Survives restarts; refreshed on each activate/heartbeat
        that carries one."""
        raw = self._store.get(self._keys.feature_keyring)
        if not raw:
            return None
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else None
        except Exception:  # noqa: BLE001
            return None

    def _state_is_foreign(self, current_license_id: Optional[str]) -> bool:
        """True when the cached contact-state belongs to a DIFFERENT license
        than the one currently installed (V2).

        We only treat it as foreign when we positively know the stored
        license_id AND it differs. An empty stored value (pre-V2 install, or
        never contacted) is NOT foreign — we don't want to harden out an
        existing single-license customer whose cache predates this field.
        """
        if not current_license_id:
            return False
        stored = self._store.get(self._keys.state_lid)
        return bool(stored) and stored != current_license_id

    def is_revoked(self, current_license_id: Optional[str] = None) -> bool:
        """Whether the server has remotely revoked this license.

        Returns True only when the flag explicitly reads '1' AND the cached
        state is not foreign (V2). Any storage error / absence returns False
        (unknown == not-revoked) — failing closed would lock legitimate users
        out during a transient storage hiccup, and ``in_offline_grace`` is the
        backstop: if the server hasn't been reached for ``offline_grace_days``
        the caller blocks regardless.

        A revoked flag left by a DIFFERENT license must not block the one now
        installed (and must not be read as authoritative for it) — so a
        foreign flag is ignored here.
        """
        if self._state_is_foreign(current_license_id):
            return False
        return self._store.get(self._keys.revoked) == '1'

    def days_since_last_contact(self) -> Optional[int]:
        last = self._store.get(self._keys.last_ok)
        if not last:
            return None
        try:
            return (datetime.now(timezone.utc) - _parse_iso(last)).days
        except ValueError:
            return None

    def _token_embedded_grace_days(self) -> Optional[int]:
        """Read ``offline_grace_days`` the server embedded in the cached token.

        The server stamps this into every signed payload precisely so the SDK
        honours the operator's current policy without an out-of-band config
        push. Returns None when absent / malformed.
        """
        payload = _decode_token_payload(self._store.get(self._keys.token))
        if not payload:
            return None
        v = payload.get('offline_grace_days')
        # bool is an int subclass — exclude it explicitly.
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            return None
        return v

    def _effective_grace_days(self) -> int:
        """Grace window actually enforced.

        Takes ``min(configured, token-embedded)`` so the token can only
        TIGHTEN the window, never loosen it: the server shrinking grace (e.g.
        a stale local default of 14d vs the server's current 3d) takes effect,
        while a forged / MITM'd token claiming ``offline_grace_days=9999``
        cannot extend usage beyond the locally configured cap. Without a valid
        embedded value we fall back to the configured default.
        """
        embedded = self._token_embedded_grace_days()
        if embedded is None:
            return self._grace_days
        return min(self._grace_days, embedded)

    def in_offline_grace(self, current_license_id: Optional[str] = None) -> bool:
        """Whether this license may keep working while the server is offline.

        V2: a successful contact recorded for a DIFFERENT license must NOT
        grant grace to the one now installed. Otherwise a leaked license
        pasted onto a host that recently activated some other license would
        ride that host's last_ok for the whole grace window without ever
        activating itself (bypassing max_nodes). Foreign state → no grace;
        this license must make its own successful contact first.
        """
        if self._state_is_foreign(current_license_id):
            return False
        days = self.days_since_last_contact()
        if days is None:
            # Never contacted — lenient on first install; the local signature
            # verifier gates this case anyway.
            return True
        return days <= self._effective_grace_days()
