"""rstlic_verifier — platform-agnostic license-token verifier for the RST
License Server (token format v0.4.0+).

This is the **verification half** of the RST licensing SDK. It pairs with
``rstlic_client.py`` (the activate / heartbeat / refresh transport) and lets
ANY product — Splunk app, plain Python backend, CLI, desktop app — validate a
signed license offline using only the per-app RSA **public** key.

Drop this file next to ``rstlic_client.py`` in your project. It depends only
on the ``cryptography`` package (already bundled by Splunk 10.x; vendor it for
9.x / non-Splunk hosts).

------------------------------------------------------------------------------
Token wire format (must match server/crypto/signing.py):

    <base64(json_payload)> '.' <base64(rsa_pss_signature)>

The payload is **plaintext JSON**; integrity is enforced by the RSA-PSS /
SHA-256 signature alone. There is no AES layer — the legacy AES-256-GCM
marketplace format was rolled back upstream and is neither produced nor
accepted here. (If you must validate ancient AES tokens, use the Splunk-app
fork's verifier; new products should not.)

Two token *kinds* share this format:
  * license token  — long-lived entitlement
                     {license_id, app_id, product, license_type, email,
                      issue_date, expiry_date, server_guid, max_nodes,
                      features, version}
  * session token  — SEC-AC-1 host binding
                     {kind:'session', license_id, app_id, fingerprint, exp}

------------------------------------------------------------------------------
Why this is NOT the Splunk verifier

The full-featured Splunk verifier (`<splunk-app>/bin/lib/license_verifier.py`)
reads public keys from ``app.conf [license]`` and runs in "remote-online"
mode (skips the local signature check, leaning entirely on phone-home). Both
of those are Splunk-deployment choices. This module instead:

  * takes the public key PEM(s) directly (no conf parsing) — wire it from
    wherever your product keeps config; a Splunk adapter can read app.conf
    and pass the bytes in.
  * verifies the RSA-PSS signature locally **by default** (``verify_signature
    _locally=True``) so a product that cannot reliably phone home is still
    protected. Set it False to mirror the Splunk remote-online posture.

------------------------------------------------------------------------------
Quick start::

    from rstlic_verifier import LicenseVerifier, LicenseError

    pub_pem = open('keys/my-product/public.pem', 'rb').read()
    verifier = LicenseVerifier(public_key_pem=pub_pem,
                               expected_product='my-product')
    try:
        payload = verifier.validate_full(license_token)
    except LicenseError as e:
        # entitlement is invalid / expired / wrong product / revoked
        ...

Or the cached convenience wrapper (recommended for hot paths)::

    from rstlic_verifier import get_cached_license_status
    status = get_cached_license_status(license_token, public_key_pem=pub_pem,
                                       expected_product='my-product')
    if status['valid']:
        payload = status['data']
"""
from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional, Union

# Splunk 10.x bundles `cryptography`; 9.x and some slim runtimes don't. Try the
# system import first and fall back to a vendored copy in ./vendor/ if present —
# this keeps the module drop-in across environments without forcing the
# vendored tree to override a (possibly newer, ABI-correct) bundled one.
try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
except ImportError:  # pragma: no cover - exercised only on bare runtimes
    import os
    import sys
    _vendor_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendor')
    if _vendor_dir not in sys.path:
        sys.path.insert(0, _vendor_dir)
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

# Embedded trust anchors (SEC-PK-1). Optional: a partially-vendored deployment
# might drop only rstlic_verifier.py without rstlic_trusted_keys.py — in that
# case trust resolution degrades to "use whatever PEMs were passed in", i.e.
# the exact legacy behaviour, so the import is best-effort.
try:
    from rstlic_trusted_keys import resolve_trusted_pems as _resolve_trusted_pems
except ImportError:  # pragma: no cover - only when the module isn't vendored
    _resolve_trusted_pems = None

# Trusted time + rollback detection (SEC-TM-1). Best-effort import: a partially
# vendored deployment without rstlic_time degrades to the local clock (the
# legacy behaviour), so time_policy other than 'local' simply has no effect.
try:
    from rstlic_time import (
        trusted_now as _trusted_now,
        check_rollback as _check_rollback,
        record_seen as _record_seen,
        lastseen_key as _lastseen_key,
        signed_time as _signed_time,
        TrustedTimeUnavailable as _TrustedTimeUnavailable,
    )
except ImportError:  # pragma: no cover - only when the module isn't vendored
    _trusted_now = _check_rollback = _record_seen = _lastseen_key = _signed_time = None

    class _TrustedTimeUnavailable(Exception):
        pass

logger = logging.getLogger('rstlic_verifier')

# Valid clock-trust policies for LicenseVerifier(time_policy=...).
_TIME_POLICIES = ('local', 'warn', 'enforce')


def _resolve_rollback_skew(explicit_seconds: Optional[int]) -> int:
    """Rollback tolerance in seconds: explicit arg > ``RSTLIC_ROLLBACK_SKEW_DAYS``
    env > 86400 (1 day). Env-tunable so ops can widen the window (to absorb a
    legitimate clock correction) without a code change."""
    if explicit_seconds is not None:
        return max(0, int(explicit_seconds))
    env = os.environ.get('RSTLIC_ROLLBACK_SKEW_DAYS')
    if env:
        try:
            return max(0, int(float(env) * 86400))
        except ValueError:
            logger.warning("invalid RSTLIC_ROLLBACK_SKEW_DAYS %r; using 1 day", env)
    return 24 * 60 * 60

# License tiers the server currently mints. Comparison is case-insensitive.
# Legacy names (starter/professional) are retained so older customer tokens
# keep validating after the server renamed tiers to 'standard'.
_ALLOWED_LICENSE_TYPES = {
    'trial', 'standard', 'starter', 'professional', 'enterprise',
}

# Minimum acceptable payload schema version. v1 (pre-RST-License-Server)
# tokens are no longer honoured.
_MIN_VERSION = 2

PemInput = Union[bytes, str]


class LicenseError(Exception):
    """Any verification, parsing, format, binding, or expiry failure."""


# Back-compat alias for callers/tests that imported the Elastic-fork name.
InvalidLicense = LicenseError


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _parse_iso(s: Any) -> datetime:
    """Parse an ISO-8601 timestamp into a tz-aware UTC datetime.

    The license server (FastAPI/Pydantic) emits timestamps with a literal Z
    suffix and fractional microseconds, e.g. '2027-04-27T14:53:20.722392Z'.
    Python 3.11+ handles the Z natively; 3.9 (Splunk-bundled) does not, so we
    normalise the suffix to an explicit +00:00 offset first.
    """
    if not isinstance(s, str):
        raise ValueError('not a string')
    s = s.strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _coerce_pem_list(public_key_pem: Union[PemInput, Iterable[PemInput]]) -> list[bytes]:
    """Normalise the constructor's public_key_pem arg into a list of bytes.

    Accepts a single PEM (bytes/str) or an iterable of them — the latter is
    the key-rotation case where a build ships both the legacy and current
    issuer keys so tokens signed by EITHER validate.
    """
    if isinstance(public_key_pem, (bytes, str)):
        items: list[PemInput] = [public_key_pem]
    else:
        items = list(public_key_pem)
    out: list[bytes] = []
    for p in items:
        if p is None:
            continue
        out.append(p if isinstance(p, bytes) else p.encode('utf-8'))
    return out


def _load_public_key(public_key_pem: bytes):
    try:
        pub = serialization.load_pem_public_key(public_key_pem)
    except Exception as e:  # noqa: BLE001
        raise LicenseError(f'failed to load public key: {e}')
    if not isinstance(pub, rsa.RSAPublicKey):
        raise LicenseError('public key is not RSA')
    return pub


# ---------------------------------------------------------------------------
# Functional layer — stateless verify/decode primitives.
# Use these directly if you don't need the constraint-checking class.
# ---------------------------------------------------------------------------
def decode_payload(token: str) -> dict[str, Any]:
    """Decode (WITHOUT verifying) the JSON payload from a token.

    Use only when the signature was already verified, or for inspection /
    debugging. For trust decisions call :func:`verify_token`.
    """
    if not token or '.' not in token:
        raise LicenseError("token must be 'base64.base64'")
    payload_b64 = token.strip().split('.', 1)[0]
    try:
        payload = json.loads(base64.b64decode(payload_b64).decode('utf-8'))
    except Exception as e:  # noqa: BLE001
        raise LicenseError(f'payload is not valid JSON: {e}')
    if not isinstance(payload, dict):
        raise LicenseError('payload is not a JSON object')
    return payload


def verify_token(token: str, public_key_pem: Union[PemInput, Iterable[PemInput]]) -> dict[str, Any]:
    """Verify a signed token's RSA-PSS signature and return its JSON payload.

    ``public_key_pem`` may be a single PEM or several (key rotation): the
    signature is accepted if ANY supplied key validates it.

    salt_length is ``PSS.AUTO`` so signatures minted by every server signer
    backend verify — LocalFileSigner uses MAX_LENGTH while AWS KMS / Vault
    Transit use hash-length (32) salt. Hardcoding either would silently
    reject tokens signed by the other path.
    """
    if not token or '.' not in token:
        raise LicenseError("token must be 'base64.base64'")
    parts = token.strip().split('.')
    if len(parts) != 2:
        raise LicenseError("token must have exactly one '.' separator")
    payload_b64, sig_b64 = parts
    try:
        sig = base64.b64decode(sig_b64)
    except Exception as e:  # noqa: BLE001
        raise LicenseError(f'signature base64 decode failed: {e}')

    pems = _coerce_pem_list(public_key_pem)
    if not pems:
        raise LicenseError('no public keys configured')

    message = payload_b64.encode('ascii')
    for pem in pems:
        # A malformed PEM in a rotation list must NOT abort the whole check —
        # skip it and try the next key (one bad entry shouldn't lock out a
        # token signed by a sibling key).
        try:
            pub = _load_public_key(pem)
        except LicenseError:
            logger.warning('skipping unparseable public key in rotation list')
            continue
        try:
            pub.verify(
                sig,
                message,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                            salt_length=padding.PSS.AUTO),
                hashes.SHA256(),
            )
            return decode_payload(token)
        except InvalidSignature:
            continue
    raise LicenseError('RSA-PSS signature verification failed')


def verify_session_token(token: str,
                         public_key_pem: Union[PemInput, Iterable[PemInput]],
                         expected_fingerprint: str,
                         expected_license_id: Optional[str] = None) -> dict[str, Any]:
    """Verify a SEC-AC-1 session token and enforce its bindings.

    Checks: RSA-PSS signature, ``kind == 'session'``, that the embedded
    ``fingerprint`` matches THIS host, AND (when ``expected_license_id`` is
    given) that the token was minted for THAT license.

    Why the license_id check matters (V1, 2026-05-30 audit): a session token
    only proves "license X was activated on this host". Without tying it to
    the license currently being validated, a cheap/free license's session
    token could vouch for a *different*, more expensive license pasted on the
    same machine — letting an attacker activate a throwaway trial on each of N
    hosts and then run one enterprise license (max_nodes=1) on all of them.
    Binding the check to license_id closes that: the trial's session token
    (license_id=trial) won't satisfy the enterprise license's binding.

    Expiry is intentionally NOT checked — host binding doesn't decay with time
    (it's the same machine); the heartbeat/refresh loop owns rotation. Use
    :func:`session_token_expiry` to decide when to pre-emptively refresh.
    """
    payload = verify_token(token, public_key_pem)
    if payload.get('kind') != 'session':
        raise LicenseError('not a session token')
    fp = payload.get('fingerprint', '')
    if not fp or fp != expected_fingerprint:
        raise LicenseError(
            'session token is bound to a different machine '
            '(hardware fingerprint mismatch) — licenses are not portable'
        )
    if expected_license_id is not None:
        tok_lid = payload.get('license_id', '')
        if not tok_lid or tok_lid != expected_license_id:
            raise LicenseError(
                'session token was issued for a different license '
                f'({tok_lid!r} != {expected_license_id!r}) — it cannot vouch '
                'for this license on this host'
            )
    return payload


def session_token_expiry(token_payload: dict[str, Any]) -> Optional[datetime]:
    """Parse a session-token payload's ``exp`` into an aware UTC datetime.

    Returns None on a missing / malformed exp rather than raising — callers
    use it only to decide when to refresh.
    """
    raw = token_payload.get('exp', '')
    try:
        return _parse_iso(str(raw))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Watermark — the server embeds wm_* fields in the signed payload so a leaked
# token can be traced to the operator who minted it. Log once per license_id
# per process: enough to surface the trail, quiet enough to not spam.
# ---------------------------------------------------------------------------
_audit_logger = logging.getLogger('rstlic.watermark')
_seen_watermark_for_license: set[str] = set()


def _log_watermark(license_data: dict[str, Any]) -> None:
    if not isinstance(license_data, dict):
        return
    license_id = license_data.get('license_id') or '<unknown>'
    if license_id in _seen_watermark_for_license:
        return
    _seen_watermark_for_license.add(license_id)
    wm = {k: v for k, v in license_data.items()
          if isinstance(k, str) and k.startswith('wm_')}
    if not wm:
        return
    try:
        kv = ' '.join('{}={}'.format(k, v) for k, v in sorted(wm.items()))
        _audit_logger.info('license_id=%s %s', license_id, kv)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# LicenseVerifier — full constraint checking on top of signature verification.
# ---------------------------------------------------------------------------
class LicenseVerifier:
    """Verify + fully validate a license token for one product.

    Parameters
    ----------
    public_key_pem:
        One PEM (bytes/str) or an iterable of them (key rotation). Required
        when ``verify_signature_locally`` is True.
    expected_product:
        The product/app_id this verifier accepts. The token's ``product``
        (alias of ``app_id``) must match. Pass None to skip the product
        check (NOT recommended for multi-product servers — a token for
        another app would otherwise validate here).
    verify_signature_locally:
        True (default) → verify the RSA-PSS signature offline. False →
        "remote-online" posture: skip the local signature check and rely on
        phone-home (activate/heartbeat) + CRL as the integrity authority,
        matching the Splunk-app deployment. Only use False when the product
        actually phones home on a tight cadence.
    crl_fetcher:
        Optional ``callable(since_iso_or_None) -> dict`` returning the
        server's CRL (revocation list). Wrap ``RSTLicClient.fetch_crl`` (or
        an equivalent) and swallow transport errors inside it.
    crl_storage:
        Optional proxy with ``get(key)`` / ``set(key, value)`` for persisting
        the CRL cache across restarts (JSON-serialisable values).
    app_id:
        Optional app/product id used ONLY to look up embedded trust anchors
        (SEC-PK-1). When the SDK ships with an embedded public key for this
        ``app_id`` (compiled into ``rstlic_trusted_keys.TRUSTED_PUBLIC_KEYS``),
        that key becomes the trust root and the ``public_key_pem`` passed here
        is treated as conf-supplied: merged in (``additive`` mode) or ignored
        unless endorsed (``authoritative`` mode). When no embedded key exists
        the passed ``public_key_pem`` is used as-is (legacy behaviour). Leave
        None to opt out of embedded-key resolution entirely.
    endorsements:
        Optional list of key-rotation endorsement bundles (see
        ``rstlic_trusted_keys``). Only consulted in ``authoritative`` mode to
        admit a new signing key that was minted after this binary was built.
    trust_mode:
        Override for ``RSTLIC_TRUST_MODE`` (``'auto'`` | ``'additive'`` |
        ``'authoritative'``). Default ``auto`` = authoritative when the app has
        an embedded key, additive otherwise.
    time_policy:
        Clock-trust policy (SEC-TM-1). Default is ``RSTLIC_TIME_POLICY`` env, or
        ``'local'``. A non-``local`` policy REQUIRES ``time_storage`` (or
        ``crl_storage``) — the constructor raises otherwise. One of:
          * ``'local'`` — use the local system clock for expiry, as before.
            No network, no rollback check. Fully back-compat.
          * ``'warn'`` — resolve a TRUSTED time (HTTPS ``Date`` + NTP fallback,
            cached) for the expiry check and detect clock rollback, but only
            LOG on rollback; never block.
          * ``'enforce'`` — same, but RAISE ``LicenseError`` on detected
            rollback. Recommended for offline / air-gapped products, where
            ``validate_offline`` has no heartbeat to lean on.

        Item C: this default ('local' unless you pass ``time_policy=``/set
        ``RSTLIC_TIME_POLICY``) only governs ``validate_full()`` / the online
        path. ``validate_offline()`` applies its OWN safer default when you
        leave this unset: 'enforce' (backed by ``time_storage``/``crl_storage``
        if either is configured) or 'warn' (loud log, no storage available) —
        never a silent 'local'. Pass ``time_policy=`` explicitly to opt back
        into 'local' for offline too.
    time_storage:
        Storage proxy (``get``/``set``) for the time cache + last-seen
        high-water mark. Defaults to ``crl_storage`` so one storage serves
        both. Rollback detection is a no-op without storage.
    time_urls / ntp_servers:
        Optional trusted-time sources. Pass your license-server's HTTPS URL as
        ``time_urls`` for the strongest guarantee. Default to public TLS hosts
        / NTP pool (overridable via ``RSTLIC_TIME_URL`` / ``RSTLIC_NTP``).
    time_strict:
        When True, a non-``local`` policy that cannot reach ANY trusted time
        source raises instead of falling back to the local clock. Default False
        (fall back to local + rollback detection).
    rollback_skew_seconds:
        Tolerance before a backwards clock move counts as rollback. Default is
        ``RSTLIC_ROLLBACK_SKEW_DAYS`` env (days), else 86400 = 1 day, absorbing
        legitimate timezone/VM-pause adjustments.
    time_ttl_seconds:
        How long a fetched trusted time is cached (default 3600).
    """

    def __init__(self, *,
                 public_key_pem: Optional[Union[PemInput, Iterable[PemInput]]] = None,
                 expected_product: Optional[str] = None,
                 verify_signature_locally: bool = True,
                 crl_fetcher: Optional[Callable[[Optional[str]], dict]] = None,
                 crl_storage: Optional[Any] = None,
                 crl_ttl_seconds: int = 24 * 60 * 60,
                 app_id: Optional[str] = None,
                 endorsements: Optional[Iterable[dict]] = None,
                 trust_mode: Optional[str] = None,
                 time_policy: Optional[str] = None,
                 time_storage: Optional[Any] = None,
                 time_urls: Optional[Iterable[str]] = None,
                 ntp_servers: Optional[Iterable[str]] = None,
                 time_strict: bool = False,
                 rollback_skew_seconds: Optional[int] = None,
                 time_ttl_seconds: int = 60 * 60,
                 signed_time_url: Optional[str] = None):
        self._pems = _coerce_pem_list(public_key_pem) if public_key_pem is not None else []
        # SEC-PK-1: fold in embedded trust anchors. resolve_trusted_pems is a
        # no-op (returns the conf pems unchanged) when the app has no embedded
        # key, so this is safe for un-provisioned apps and back-compat.
        if app_id and _resolve_trusted_pems is not None:
            self._pems = _resolve_trusted_pems(
                app_id, self._pems, endorsements=endorsements, mode=trust_mode)
        self._expected_product = expected_product
        self._verify_sig = verify_signature_locally
        if self._verify_sig and not self._pems:
            raise LicenseError(
                'verify_signature_locally=True requires public_key_pem; '
                'pass the per-product RSA public key, or set '
                'verify_signature_locally=False for remote-online mode'
            )
        # CRL state is per-instance (not module-global) so two verifiers for
        # different products don't share a revocation set.
        self._crl_fetcher = crl_fetcher
        self._crl_storage = crl_storage
        self._crl_ttl = crl_ttl_seconds
        self._crl = {'revoked_ids': set(), 'last_fetched_ts': 0.0, 'last_since': ''}
        if crl_storage is not None:
            self._load_crl_from_storage()

        # -- trusted time / rollback (SEC-TM-1) --------------------------------
        # Policy: explicit arg > RSTLIC_TIME_POLICY env > 'local'. Env-tunable
        # so ops can escalate warn->enforce (or relax) without a code change.
        # Item C: remember whether the CALLER actually chose a policy (arg or
        # env) as opposed to us defaulting it — validate_offline() uses this to
        # decide whether it's safe to upgrade its OWN default (see
        # _offline_time_policy below) without stepping on an explicit choice.
        self._time_policy_explicit = (
            time_policy is not None or bool(os.environ.get('RSTLIC_TIME_POLICY')))
        policy = (time_policy
                  or os.environ.get('RSTLIC_TIME_POLICY')
                  or 'local').strip().lower()
        if policy not in _TIME_POLICIES:
            logger.warning("unknown time_policy %r; using 'local'", policy)
            policy = 'local'
        self._time_policy = policy
        self._time_storage = time_storage if time_storage is not None else crl_storage
        # SEC-TM-1 footgun guard: a non-local policy without storage would (a)
        # hit the network on EVERY validate_full (no time cache) and (b) make
        # rollback detection a silent no-op. Fail loud at construction instead.
        if self._time_policy != 'local' and self._time_storage is None:
            raise LicenseError(
                "time_policy=%r requires a storage backend for the trusted-time "
                "cache and rollback high-water mark; pass time_storage= (or "
                "crl_storage=). Use a FileStorage/MemoryStorage from "
                "rstlic_storage." % self._time_policy)
        self._time_urls = list(time_urls) if time_urls else None
        self._ntp_servers = list(ntp_servers) if ntp_servers else None
        self._time_strict = bool(time_strict)
        self._time_ttl = time_ttl_seconds
        self._rollback_skew = timedelta(seconds=_resolve_rollback_skew(rollback_skew_seconds))
        # SEC-TM-1 strongest source: a signed-time endpoint verified with THIS
        # verifier's trusted keys (can't be spoofed via a cert for another host).
        self._signed_time_url = signed_time_url or os.environ.get('RSTLIC_SIGNED_TIME_URL') or None

    # -- CRL plumbing -------------------------------------------------------
    def _load_crl_from_storage(self) -> None:
        try:
            raw = self._crl_storage.get('rstlic_crl_cache')
            if not raw:
                return
            blob = json.loads(raw) if isinstance(raw, str) else raw
            self._crl['revoked_ids'] = set(blob.get('revoked_ids') or [])
            self._crl['last_fetched_ts'] = float(blob.get('last_fetched_ts') or 0)
            self._crl['last_since'] = blob.get('last_since') or ''
        except Exception as e:  # noqa: BLE001
            logger.info('CRL cache load failed (will refetch): %s', e)

    def _save_crl_to_storage(self) -> None:
        if self._crl_storage is None:
            return
        try:
            self._crl_storage.set('rstlic_crl_cache', json.dumps({
                'revoked_ids':     sorted(self._crl['revoked_ids']),
                'last_fetched_ts': self._crl['last_fetched_ts'],
                'last_since':      self._crl['last_since'],
            }))
        except Exception as e:  # noqa: BLE001
            logger.info('CRL cache save failed (non-fatal): %s', e)

    def _refresh_crl_if_due(self) -> None:
        if self._crl_fetcher is None:
            return
        now = time.time()
        if now - self._crl['last_fetched_ts'] < self._crl_ttl:
            return
        try:
            resp = self._crl_fetcher(self._crl['last_since'] or None)
        except Exception as e:  # noqa: BLE001 — stale cache beats no cache
            logger.info('CRL refresh skipped (server unreachable): %s', e)
            return
        if not isinstance(resp, dict):
            return
        for entry in (resp.get('revoked') or []):
            lid = entry.get('license_id') if isinstance(entry, dict) else None
            if lid:
                self._crl['revoked_ids'].add(lid)
        self._crl['last_fetched_ts'] = now
        next_since = resp.get('next_since') or resp.get('as_of')
        if next_since:
            self._crl['last_since'] = next_since
        self._save_crl_to_storage()

    # -- individual checks --------------------------------------------------
    @staticmethod
    def _validate_schema(license_data: dict[str, Any]) -> None:
        """Enforce payload shape BEFORE constraint checks rely on it."""
        license_type = license_data.get('license_type', '')
        if (not isinstance(license_type, str)
                or license_type.strip().lower() not in _ALLOWED_LICENSE_TYPES):
            raise LicenseError('Unsupported license_type. Please request an updated license.')

        expiry_str = license_data.get('expiry_date')
        if not expiry_str or not isinstance(expiry_str, str):
            raise LicenseError('License missing expiry_date')
        try:
            _parse_iso(expiry_str)
        except (ValueError, TypeError):
            raise LicenseError('expiry_date is not a valid ISO datetime')

        server_guid = license_data.get('server_guid')
        if not isinstance(server_guid, str) or not server_guid.strip():
            raise LicenseError('server_guid must be a non-empty string')

        product = license_data.get('product')
        if not isinstance(product, str) or not product.strip():
            raise LicenseError('product must be a non-empty string')

        version = license_data.get('version')
        if not isinstance(version, int) or isinstance(version, bool) or version < _MIN_VERSION:
            raise LicenseError(f'License version must be an integer >= {_MIN_VERSION}')

    @staticmethod
    def check_expiry(license_data: dict[str, Any], *,
                     now: Optional[datetime] = None) -> bool:
        """Validate expiry / issue-date against ``now`` (default: the local
        clock). Callers that resolved a TRUSTED time (SEC-TM-1) pass it in so a
        rolled-back local clock can't defeat the expiry check."""
        expiry_str = license_data.get('expiry_date')
        if not expiry_str:
            raise LicenseError('License missing expiry_date')
        try:
            expiry = _parse_iso(expiry_str)
        except ValueError:
            raise LicenseError('Invalid expiry_date format')
        if now is None:
            now = datetime.now(timezone.utc)
        if now > expiry:
            raise LicenseError('License has expired')
        issue_str = license_data.get('issue_date')
        if issue_str:
            try:
                issue = _parse_iso(issue_str)
                if issue > now + timedelta(hours=24):
                    raise LicenseError('License issue_date is in the future')
            except LicenseError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.debug('Could not parse issue_date: %s', e)
        return True

    # -- trusted time / rollback (SEC-TM-1) ---------------------------------
    def _resolve_now(self, *, policy: Optional[str] = None,
                     storage: Optional[Any] = None) -> tuple[datetime, bool]:
        """Return ``(now, trusted)`` per the effective time policy. ``local``
        policy (or a partially-vendored SDK without rstlic_time) uses the local
        clock untrusted; otherwise a trusted time is fetched + cached.

        ``policy``/``storage`` let a caller (currently only
        :meth:`validate_offline`, via Item C's offline default) evaluate a
        DIFFERENT policy/storage for a single call than this instance was
        constructed with, without mutating shared state. Default to the
        instance's own configuration when omitted.
        """
        policy = self._time_policy if policy is None else policy
        storage = self._time_storage if storage is None else storage
        if policy == 'local' or _trusted_now is None:
            return datetime.now(timezone.utc), False
        # Prefer the signed-time endpoint (verified with our trusted keys) over a
        # plain HTTPS Date header — it can't be spoofed by a cert for some other
        # host that an env override might point at.
        verified_fetcher = None
        if self._signed_time_url and _signed_time is not None and self._pems:
            verified_fetcher = lambda: _signed_time(self._signed_time_url, self._pems)
        try:
            return _trusted_now(
                storage,
                time_urls=self._time_urls,
                ntp_servers=self._ntp_servers,
                ttl=self._time_ttl,
                strict=self._time_strict,
                verified_fetcher=verified_fetcher,
            )
        except _TrustedTimeUnavailable as e:
            # strict mode: refuse rather than silently trust the local clock.
            raise LicenseError(f'Trusted time source unavailable: {e}')

    def _rollback_guard(self, license_data: dict[str, Any],
                        now: datetime, trusted: bool, *,
                        policy: Optional[str] = None,
                        storage: Optional[Any] = None) -> None:
        """Detect a rolled-back clock for offline grace abuse. Only meaningful
        when the time was NOT trusted (a trusted time can't be rolled back); a
        trusted reading still advances the last-seen high-water mark.

        ``policy``/``storage`` mirror :meth:`_resolve_now` — see its docstring.
        """
        policy = self._time_policy if policy is None else policy
        storage = self._time_storage if storage is None else storage
        if policy == 'local' or storage is None:
            return
        if _check_rollback is None or _lastseen_key is None:
            return
        key = _lastseen_key(license_data.get('license_id'))
        if not trusted and _check_rollback(storage, key, now,
                                           skew=self._rollback_skew):
            if policy == 'enforce':
                raise LicenseError(
                    'System clock rollback detected — refusing to validate '
                    'license. Set the clock correctly or reconnect to a trusted '
                    'time source.'
                )
            logger.warning('rstlic: system clock rollback detected (warn mode)')
        if _record_seen is not None:
            _record_seen(storage, key, now)

    def _offline_time_policy(self) -> tuple[str, Optional[Any]]:
        """Item C — the (policy, storage) :meth:`validate_offline` should use
        for THIS call when the caller never explicitly configured
        ``time_policy`` (arg or ``RSTLIC_TIME_POLICY`` env).

        Air-gapped offline licenses have no heartbeat/phone-home to catch a
        rolled-back clock the way the online path does, so silently falling
        back to ``'local'`` (no rollback check at all) is NOT an acceptable
        default here — unlike validate_full()/the online heartbeat path, which
        keeps 'local' as its default on purpose (server time already catches
        rollback there).

        Prefers ``'enforce'`` backed by whatever storage this verifier already
        has (``time_storage``, falling back to ``crl_storage`` — see
        ``__init__``) so the high-water mark persists across restarts. If NO
        storage was configured at all there is nowhere to persist the mark, so
        we degrade to ``'warn'`` (local clock, loud log) rather than either (a)
        raising at call time — that would turn a previously-optional arg into
        a hard requirement for every offline product — or (b) silently doing
        'local' with zero rollback protection.
        """
        if self._time_storage is not None:
            return 'enforce', self._time_storage
        logger.warning(
            "rstlic: validate_offline() called without an explicit time_policy "
            "and without time_storage/crl_storage configured -- clock-rollback "
            "detection is DISABLED for this offline license (SEC-TM-1 / Item "
            "C). Pass time_storage=FileStorage(...) (or crl_storage=) to close "
            "this gap; falling back to 'warn' (local clock only)."
        )
        return 'warn', None

    def check_product(self, license_data: dict[str, Any],
                      expected_product: Optional[str] = None) -> bool:
        product = expected_product if expected_product is not None else self._expected_product
        if product is None:
            return True  # caller opted out of the product check
        licensed_product = license_data.get('product', '')
        if not licensed_product:
            raise LicenseError('License is too old, please request an updated license')
        if licensed_product != product:
            raise LicenseError(
                f"License is for product '{licensed_product}', expected '{product}'"
            )
        return True

    @staticmethod
    def check_server_guid(license_data: dict[str, Any],
                          server_guid: Optional[str]) -> bool:
        """Enforce host binding embedded in the license payload.

        Server-issued tokens carry the sentinel ``'UNBOUND'`` because the
        license server does not know the customer's host at issue time —
        exclusivity is instead enforced server-side via host_fingerprint
        uniqueness (max_nodes). 'UNBOUND' is therefore accepted as a
        wildcard. If you pass ``server_guid=None`` the check is skipped
        entirely (the common case for products that bind via the SEC-AC-1
        session token instead — see :func:`verify_session_token`).
        """
        if server_guid is None:
            return True
        licensed_guid = license_data.get('server_guid', '')
        if not licensed_guid:
            raise LicenseError('License missing server_guid')
        if licensed_guid.upper() == 'UNBOUND':
            return True
        if licensed_guid.upper() != server_guid.upper():
            raise LicenseError(
                f'License is for server {licensed_guid}, '
                f'but this server is {server_guid}'
            )
        return True

    # -- the entry point ----------------------------------------------------
    def validate_full(self, license_key: str, *,
                      server_guid: Optional[str] = None,
                      expected_product: Optional[str] = None,
                      _allow_offline_unchecked: bool = False,
                      _time_policy_override: Optional[str] = None,
                      _time_storage_override: Optional[Any] = None) -> dict[str, Any]:
        """Full validation pipeline. Returns the validated payload or raises.

        Steps: (1) signature [unless remote-online], (2) decode, (3) schema,
        (4) reject offline tokens (host binding must be enforced via
        :meth:`validate_offline`), (5) version/expiry/product/server_guid,
        (6) CRL revocation, (7) watermark log.

        ``_allow_offline_unchecked`` is an INTERNAL flag set only by
        :meth:`validate_offline`, which performs the ``bound_fingerprint``
        check itself right after. Public callers must never set it.

        ``_time_policy_override`` / ``_time_storage_override`` are likewise
        INTERNAL — set only by :meth:`validate_offline` (Item C) to apply its
        own safer default time policy for a single call without mutating this
        instance's configuration (which still governs validate_full()'s own
        online/default behaviour unchanged). Public callers must never set
        them; use the constructor's ``time_policy=`` instead.
        """
        if not license_key or '.' not in license_key:
            raise LicenseError('Invalid license format: expected <payload>.<signature>')

        if self._verify_sig:
            # verify_token both checks the signature AND returns the payload.
            license_data = verify_token(license_key, self._pems)
        else:
            # Remote-online posture: trust phone-home for integrity; just decode.
            license_data = decode_payload(license_key)

        self._validate_schema(license_data)

        # SEC — fail closed on offline tokens (H-2). An offline token carries
        # its host lock as ``bound_fingerprint`` in the signed payload; there
        # is no /activate round trip, so the ONLY place that lock is enforced
        # is validate_offline()'s constant-time fingerprint compare. If an
        # offline token reached validate_full() (directly, or via the cached
        # get_cached_license_status fast path), returning it valid would let
        # anyone copy the license file to a different machine and pass. Refuse
        # here — the binding check is not optional.
        if not _allow_offline_unchecked and license_data.get('mode') == 'offline':
            raise LicenseError(
                'This is an OFFLINE (host-bound) license. Call '
                'validate_offline(host_fingerprint=...) so the embedded host '
                'binding is enforced; validate_full() does not check '
                'bound_fingerprint.'
            )

        version = license_data.get('version', 1)
        if not isinstance(version, int) or version < _MIN_VERSION:
            raise LicenseError('License version too old. Please request a new license.')
        # SEC-TM-1: resolve a trusted time (when policy != 'local') so a
        # rolled-back local clock can't defeat expiry / offline grace.
        now, trusted = self._resolve_now(policy=_time_policy_override,
                                         storage=_time_storage_override)
        self.check_expiry(license_data, now=now)
        self._rollback_guard(license_data, now, trusted,
                             policy=_time_policy_override,
                             storage=_time_storage_override)
        self.check_server_guid(license_data, server_guid)
        self.check_product(license_data, expected_product)

        try:
            self._refresh_crl_if_due()
        except Exception as e:  # noqa: BLE001 — never fail validation on a CRL glitch
            logger.info('CRL refresh swallowed: %s', e)
        license_id = license_data.get('license_id')
        if license_id and license_id in self._crl['revoked_ids']:
            raise LicenseError(
                'License has been revoked. Please contact support for a replacement.'
            )

        _log_watermark(license_data)
        return license_data

    def validate_offline(self, license_key: str, *,
                         host_fingerprint: str,
                         expected_product: Optional[str] = None) -> dict[str, Any]:
        """Validate an air-gapped OFFLINE license and ENFORCE its host binding.

        Offline tokens (minted by ``rstlic issue-offline``) carry the binding
        baked into the signed payload: ``mode='offline'`` plus a
        ``bound_fingerprint``. Unlike the online flow there is no /activate
        round trip or session token, so the host lock can only be enforced
        right here, on the client, by comparing the embedded fingerprint to
        THIS host's fingerprint (compute it with
        ``rstlic_client.RSTLicenseClient.fingerprint()`` and pass it in — same
        contract as the online ``validate_session_binding``).

        Steps: (1) full validation (signature / schema / expiry / product /
        CRL — via :meth:`validate_full` with ``server_guid=None`` since offline
        tokens are UNBOUND at the server-guid level), (2) assert the token is
        actually an offline token, (3) constant-time compare the bound
        fingerprint to ``host_fingerprint``.

        Raises :class:`LicenseError` if it is not an offline token, is missing
        the binding, or is bound to a DIFFERENT host (the copy-the-license-file-
        to-another-box attack). Returns the validated payload on success.
        """
        if not host_fingerprint or not isinstance(host_fingerprint, str):
            raise LicenseError('host_fingerprint is required to validate an offline license')

        # Item C (SEC-TM-1 offline rollback default): if the caller explicitly
        # configured time_policy (arg or RSTLIC_TIME_POLICY env), honour that
        # choice unchanged — including 'local', if that's really what they
        # asked for. Otherwise apply this method's OWN safer default (enforce
        # when storage exists, else warn) rather than silently inheriting the
        # online-appropriate 'local' default. This never touches self._time_*
        # so validate_full()'s own default behaviour is unaffected.
        if self._time_policy_explicit:
            _policy, _storage = self._time_policy, self._time_storage
        else:
            _policy, _storage = self._offline_time_policy()

        payload = self.validate_full(
            license_key, server_guid=None, expected_product=expected_product,
            # Bypass validate_full's offline-token refusal: WE enforce the
            # host binding via the bound_fingerprint compare just below.
            _allow_offline_unchecked=True,
            _time_policy_override=_policy,
            _time_storage_override=_storage,
        )

        if payload.get('mode') != 'offline':
            raise LicenseError(
                'Not an offline license. Use validate_full() / the online '
                'activation flow for this token.'
            )

        bound = payload.get('bound_fingerprint')
        if not bound or not isinstance(bound, str):
            raise LicenseError('Offline license is missing its host binding (bound_fingerprint)')

        # Constant-time, case-insensitive compare of the two 64-hex fingerprints.
        if not hmac.compare_digest(bound.strip().lower(), host_fingerprint.strip().lower()):
            raise LicenseError(
                'Offline license is bound to a different host. This license '
                'cannot be used on this machine — request a new offline license '
                'for this host.'
            )
        return payload

    @staticmethod
    def days_remaining(license_data: dict[str, Any]) -> int:
        expiry_str = license_data.get('expiry_date')
        if not expiry_str:
            return 0
        try:
            expiry = _parse_iso(expiry_str)
            return max(0, (expiry - datetime.now(timezone.utc)).days)
        except Exception as e:  # noqa: BLE001
            logger.debug('Could not parse expiry_date for days_remaining: %s', e)
            return 0


# ---------------------------------------------------------------------------
# Cached convenience wrapper — module-level, keyed by (token, server_guid,
# product). Asymmetric TTLs + a sticky "last-good" slot so a transient parse /
# network blip does not lock a legitimate user out. Mirrors the Splunk
# verifier's semantics so behaviour is consistent across products.
# ---------------------------------------------------------------------------
_CACHE: dict[str, Any] = {'data': None, 'valid': False, 'error': None, 'ts': 0,
                          'key': None, 'guid': None, 'product': None, 'app': None}
_CACHE_TTL = 300          # valid results
_CACHE_TTL_INVALID = 30   # invalid results — short, so blips clear fast
_LAST_GOOD: dict[str, Any] = {'data': None, 'ts': 0, 'key': None, 'guid': None,
                              'product': None, 'app': None}
_LAST_GOOD_TTL = 60 * 60  # 60 minutes

# Definitive (user-actionable) failures bypass last-good and surface
# immediately; everything else is treated as transient.
_DEFINITIVE_MARKERS = (
    'License has expired',
    'License is for server',
    'License missing expiry_date',
    'Invalid expiry_date format',
    'License missing server_guid',
    'License is for product',
    'License version too old',
    'License is too old',
    'Unsupported license_type',
    'expiry_date is not a valid ISO datetime',
    'server_guid must be a non-empty string',
    'product must be a non-empty string',
    'License version must be an integer',
    'License issue_date is in the future',
    'License has been revoked',
    'RSA-PSS signature verification failed',
    'System clock rollback detected',
    # H-2: offline token reached the online/cached path — a user-actionable
    # refusal, never a transient blip (must not serve last-good).
    'This is an OFFLINE',
    # Item E: a lost/misconfigured trust anchor (no public_key_pem at all) is
    # a definitive, user-actionable failure — NOT a transient blip. Without
    # this marker _is_transient() would treat the LicenseError raised by
    # __init__ / get_cached_license_status's throwaway-verifier construction
    # as transient, letting a stale last-good cache mask the loss of trust for
    # up to _LAST_GOOD_TTL (60 min) instead of failing closed immediately.
    'requires public_key_pem',
)


def _is_transient(exc: Exception) -> bool:
    if not isinstance(exc, LicenseError):
        return True  # network / KV / unexpected — transient by definition
    msg = str(exc)
    return not any(marker in msg for marker in _DEFINITIVE_MARKERS)


def get_cached_license_status(license_key: str, *,
                              public_key_pem: Optional[Union[PemInput, Iterable[PemInput]]] = None,
                              expected_product: Optional[str] = None,
                              server_guid: Optional[str] = None,
                              verify_signature_locally: bool = True,
                              verifier: Optional[LicenseVerifier] = None,
                              app_id: Optional[str] = None,
                              endorsements: Optional[Iterable[dict]] = None,
                              trust_mode: Optional[str] = None) -> dict[str, Any]:
    """Validate with module-level caching. Returns
    ``{'valid': bool, 'error': str|None, 'data': dict|None}``.

    Pass either a preconfigured ``verifier`` (preferred — lets it own CRL
    state) or the ``public_key_pem`` + flags to build a throwaway one. When
    building a throwaway verifier, ``app_id`` / ``endorsements`` / ``trust_mode``
    select the embedded trust anchors (SEC-PK-1); they're ignored when a
    preconfigured ``verifier`` is supplied (it already resolved its trust).
    """
    global _CACHE, _LAST_GOOD
    now = time.time()
    same = (_CACHE.get('key') == license_key
            and _CACHE.get('guid') == server_guid
            and _CACHE.get('product') == expected_product
            and _CACHE.get('app') == app_id)
    if _CACHE['ts'] and same:
        ttl = _CACHE_TTL if _CACHE['valid'] else _CACHE_TTL_INVALID
        if (now - _CACHE['ts']) < ttl:
            return {'valid': _CACHE['valid'], 'error': _CACHE['error'], 'data': _CACHE['data']}

    def _serve_last_good(reason: Exception):
        lg = (_LAST_GOOD.get('key') == license_key
              and _LAST_GOOD.get('guid') == server_guid
              and _LAST_GOOD.get('product') == expected_product
              and _LAST_GOOD.get('app') == app_id)
        if (lg and _LAST_GOOD['data'] is not None
                and (now - _LAST_GOOD['ts']) < _LAST_GOOD_TTL):
            logger.warning('license check failed transiently (%s); serving last-good', reason)
            return {'valid': True, 'data': _LAST_GOOD['data'],
                    'error': 'using last-good (transient)'}
        return None

    try:
        v = verifier or LicenseVerifier(
            public_key_pem=public_key_pem,
            expected_product=expected_product,
            verify_signature_locally=verify_signature_locally,
            app_id=app_id,
            endorsements=endorsements,
            trust_mode=trust_mode,
        )
        data = v.validate_full(license_key, server_guid=server_guid,
                               expected_product=expected_product)
    except LicenseError as e:
        if _is_transient(e):
            served = _serve_last_good(e)
            if served is not None:
                return served
        _CACHE = {'data': None, 'valid': False, 'error': str(e), 'ts': now,
                  'key': license_key, 'guid': server_guid, 'product': expected_product,
                  'app': app_id}
        return {'valid': False, 'error': str(e), 'data': None}
    except Exception as e:  # noqa: BLE001 — non-LicenseError == transient
        served = _serve_last_good(e)
        if served is not None:
            return served
        msg = 'License verification temporarily unavailable'
        _CACHE = {'data': None, 'valid': False, 'error': msg, 'ts': now,
                  'key': license_key, 'guid': server_guid, 'product': expected_product,
                  'app': app_id}
        return {'valid': False, 'error': msg, 'data': None}

    _CACHE = {'data': data, 'valid': True, 'error': None, 'ts': now,
              'key': license_key, 'guid': server_guid, 'product': expected_product,
              'app': app_id}
    _LAST_GOOD = {'data': data, 'ts': now, 'key': license_key,
                  'guid': server_guid, 'product': expected_product, 'app': app_id}
    return {'valid': True, 'error': None, 'data': data}


def invalidate_cache() -> None:
    """Clear the module-level cache (e.g. after activating a new license)."""
    global _CACHE, _LAST_GOOD
    _CACHE = {'data': None, 'valid': False, 'error': None, 'ts': 0,
              'key': None, 'guid': None, 'product': None, 'app': None}
    _LAST_GOOD = {'data': None, 'ts': 0, 'key': None, 'guid': None,
                  'product': None, 'app': None}
