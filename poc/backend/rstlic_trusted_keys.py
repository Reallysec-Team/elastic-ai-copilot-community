"""Embedded trust anchors for the RST License SDK (SEC-PK-1).

Holds the AUTHORITATIVE per-app RSA **public** keys that are compiled into the
``.so`` / ``.pyd`` so the signature trust root ships *inside the binary* rather
than in an editable ``app.conf [license]`` stanza.

Why this exists
---------------
Before this module the only trust root was ``public_key_pem`` read from
``app.conf [license]`` (see ``rstlic_splunk_verifier._load_keys_from_conf``).
An attacker who can edit ``app.conf`` could swap in *their own* public key and
then self-sign a forged ``enterprise`` license — every downstream check
(``validate_full``) would then pass. That defeats the entire RSA-PSS scheme
without even patching the compiled verifier.

With an embedded key the conf can no longer introduce a new trust anchor on its
own. A new key is accepted from conf **only** when it carries an *endorsement*
(a small bundle counter-signed by an already-trusted embedded key) — preserving
zero-downtime key rotation without re-trusting raw, attacker-editable PEMs.

Provisioning model (per-app, build-time injection)
--------------------------------------------------
``TRUSTED_PUBLIC_KEYS`` is intentionally **empty** in the source tree. The
per-platform Cython build matrix writes the right app's public PEM(s) into this
map *before* ``cythonize`` (see ``_setup_cython.py``), so the key is baked into
the binary that ships. An empty map means **"not provisioned"**: the SDK then
falls back to the legacy ``app.conf`` behaviour, so this file is safe to ship
un-provisioned and adopt one app at a time (grayscale).

Trust modes (env ``RSTLIC_TRUST_MODE``)
---------------------------------------
* ``auto`` (default) — **secure-when-hardened**: resolves to ``authoritative``
  for an app that HAS an embedded key (baking a key in is the operator's
  explicit hardening signal), and to ``additive`` for one that doesn't. So a
  binary shipped with embedded keys gets the hardened posture automatically,
  while an un-provisioned binary is never bricked — no extra env var needed.
* ``additive`` — trust = embedded keys ∪ raw conf keys. The compatibility
  escape hatch (e.g. during a staged rollout).
* ``authoritative`` — trust = embedded keys ∪ keys *endorsed* by an embedded
  key. Raw conf keys are ignored. This is the hardened posture that closes the
  key-swap attack.

If ``authoritative`` is requested for an app with **no** embedded key the SDK
warns and falls back to the conf keys (so a misconfiguration never bricks an
un-provisioned app).

This module depends only on ``cryptography`` and the standard library so it can
be vendored standalone next to ``rstlic_verifier.py``.
"""
from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone
from typing import Iterable, Optional, Union

# Mirror rstlic_verifier's import-with-vendor-fallback so this module is
# drop-in on bare runtimes (Splunk 9.x) that ship a vendored ``cryptography``.
try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
except ImportError:  # pragma: no cover - exercised only on bare runtimes
    import sys
    _vendor_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendor')
    if _vendor_dir not in sys.path:
        sys.path.insert(0, _vendor_dir)
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

logger = logging.getLogger('rstlic_trusted_keys')

PemInput = Union[bytes, str]

# ---------------------------------------------------------------------------
# Embedded trust anchors. POPULATED AT BUILD TIME, per app. Keep EMPTY in git.
#
#   TRUSTED_PUBLIC_KEYS = {
#       'ai-query-assistant-for-splunk': [b"-----BEGIN PUBLIC KEY-----\n..."],
#   }
#
# Values may be PEM bytes or str; mixed lists are fine.
#
# The line below is the build-time injection anchor: _embed_keys.inject()
# rewrites `= {}` into the populated literal just before cythonize, then the
# build restores it. Keep it on ONE line and EMPTY in git.
# ---------------------------------------------------------------------------
TRUSTED_PUBLIC_KEYS: dict[str, list[PemInput]] = {}  # RSTLIC_EMBED_ANCHOR

_VALID_MODES = ('auto', 'additive', 'authoritative')

# Domain-separation prefix so an endorsement signature can never be replayed as
# a license-token signature (and vice-versa) — they sign disjoint byte spaces.
_ENDORSE_DOMAIN = b'rstlic-key-endorsement-v1\x00'


def _to_bytes(pem: PemInput) -> bytes:
    return pem if isinstance(pem, bytes) else pem.encode('utf-8')


def _spki_der(pem: PemInput) -> bytes:
    """SubjectPublicKeyInfo DER of an RSA public PEM — the stable, whitespace-
    insensitive byte form a kid / endorsement signs over."""
    pub = serialization.load_pem_public_key(_to_bytes(pem))
    if not isinstance(pub, rsa.RSAPublicKey):
        raise ValueError('public key is not RSA')
    return pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def key_id(pem: PemInput) -> str:
    """Short, stable identifier for a public key: first 16 hex of the SHA-256 of
    its SPKI DER. Used to tell embedded / endorsed keys apart during rotation."""
    digest = hashes.Hash(hashes.SHA256())
    digest.update(_spki_der(pem))
    return digest.finalize().hex()[:16]


def trust_mode(explicit: Optional[str] = None) -> str:
    """Resolve the configured trust mode: explicit arg > ``RSTLIC_TRUST_MODE``
    env > ``auto``. Returns one of ``auto`` / ``additive`` / ``authoritative``
    (``auto`` is resolved against embedded-key presence by
    :func:`_effective_mode`). An unrecognised value falls back to ``auto`` with
    a warning rather than failing closed."""
    mode = (explicit or os.environ.get('RSTLIC_TRUST_MODE') or 'auto').strip().lower()
    if mode not in _VALID_MODES:
        logger.warning("unknown RSTLIC_TRUST_MODE %r; using 'auto'", mode)
        return 'auto'
    return mode


def _effective_mode(explicit: Optional[str], has_embedded: bool) -> str:
    """Resolve ``auto`` to a concrete mode: ``authoritative`` when the app has
    an embedded trust anchor (the operator deliberately baked a key in, so honor
    it as the sole root), ``additive`` otherwise (un-provisioned → never break
    an app that still relies on app.conf). Explicit ``additive`` /
    ``authoritative`` always win."""
    mode = trust_mode(explicit)
    if mode == 'auto':
        return 'authoritative' if has_embedded else 'additive'
    return mode


def get_embedded_keys(app_id: Optional[str]) -> list[bytes]:
    """The embedded trust anchors for ``app_id`` as a list of PEM bytes (empty
    if the app is not provisioned or ``app_id`` is None)."""
    if not app_id:
        return []
    return [_to_bytes(p) for p in TRUSTED_PUBLIC_KEYS.get(app_id, []) if p]


# ---------------------------------------------------------------------------
# Endorsement (counter-signed key-rotation bundle)
# ---------------------------------------------------------------------------
# Wire shape (JSON object), produced by the server's
# ``signing.make_key_endorsement`` and carried in app.conf as
# ``endorsed_key_pem = <base64(json bundle)>``:
#
#   {
#     "new_pub":     "<PEM string of the RSA public key being authorised>",
#     "kid":         "<key_id(new_pub) — informational/operational>",
#     "not_before":  "<ISO-8601 UTC, or '' for immediately valid>",
#     "sig":         "<base64 RSA-PSS signature by a TRUSTED key>"
#   }
#
# The signed message is domain-prefixed SPKI DER + NUL + not_before, so the
# signature commits to the exact key bytes regardless of PEM whitespace.
# ---------------------------------------------------------------------------
def endorsement_message(new_pub: PemInput, not_before: str = '') -> bytes:
    """The exact bytes an endorsement signs. MUST match the server signer."""
    return _ENDORSE_DOMAIN + _spki_der(new_pub) + b'\x00' + (not_before or '').encode('utf-8')


def _parse_iso(s: str) -> datetime:
    s = s.strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def verify_key_endorsement(bundle: dict, trusted_pems: Iterable[PemInput]) -> Optional[bytes]:
    """Return the endorsed public PEM (bytes) if ``bundle`` is validly endorsed
    by ANY of ``trusted_pems`` and is already in effect; otherwise None.

    Never raises on a malformed / forged bundle — a bad endorsement is simply
    "not trusted", not a crash. ``not_before`` gating uses the local clock; it
    is operator-controlled (not an attacker-controlled expiry), so a trusted
    time source is unnecessary here.
    """
    if not isinstance(bundle, dict):
        return None
    new_pub = bundle.get('new_pub')
    sig_b64 = bundle.get('sig')
    if not new_pub or not sig_b64:
        return None
    not_before = str(bundle.get('not_before') or '')
    try:
        new_pub_bytes = _to_bytes(new_pub)
        message = endorsement_message(new_pub_bytes, not_before)
        sig = base64.b64decode(sig_b64)
    except Exception:  # noqa: BLE001 — any decode/parse failure => not trusted
        return None

    if not_before:
        try:
            if datetime.now(timezone.utc) < _parse_iso(not_before):
                return None  # endorsement not yet in effect
        except (ValueError, TypeError):
            return None

    for pem in trusted_pems:
        try:
            pub = serialization.load_pem_public_key(_to_bytes(pem))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(pub, rsa.RSAPublicKey):
            continue
        try:
            pub.verify(
                sig,
                message,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                            salt_length=padding.PSS.AUTO),
                hashes.SHA256(),
            )
            return new_pub_bytes
        except InvalidSignature:
            continue
    return None


# ---------------------------------------------------------------------------
# Trust resolution — the single entry point the verifier / adapter call.
# ---------------------------------------------------------------------------
def _dedupe(pems: Iterable[bytes]) -> list[bytes]:
    out: list[bytes] = []
    seen: set[bytes] = set()
    for p in pems:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def resolve_trusted_pems(app_id: Optional[str],
                         conf_pems: Iterable[PemInput],
                         *,
                         endorsements: Optional[Iterable[dict]] = None,
                         mode: Optional[str] = None) -> list[bytes]:
    """Compute the set of public keys to trust for ``app_id``.

    Mode resolution (``auto`` is the default — see :func:`_effective_mode`):

    * No embedded keys for the app  -> return ``conf_pems`` unchanged (legacy /
      un-provisioned fallback — ``auto`` resolves to additive, never bricks an
      un-provisioned app). An EXPLICIT ``authoritative`` with no embedded key
      logs a warning (misconfiguration) and still falls back to conf.
    * ``additive``                  -> embedded ∪ conf.
    * ``authoritative`` (incl. ``auto`` + embedded present) -> embedded ∪ keys
      endorsed by an embedded key; raw conf keys are dropped.
    """
    conf = [_to_bytes(p) for p in conf_pems if p]
    embedded = get_embedded_keys(app_id)
    if not embedded:
        explicit = trust_mode(mode)
        if explicit == 'authoritative':
            logger.warning(
                'RSTLIC_TRUST_MODE=authoritative but no embedded key for app %r; '
                'falling back to app.conf keys', app_id)
        return _dedupe(conf)

    resolved_mode = _effective_mode(mode, has_embedded=True)
    if resolved_mode == 'additive':
        return _dedupe(embedded + conf)

    # authoritative (explicit, or auto with an embedded key): embedded +
    # endorsed-by-embedded; raw conf keys ignored.
    trusted = list(embedded)
    for bundle in (endorsements or []):
        endorsed = verify_key_endorsement(bundle, embedded)
        if endorsed is not None:
            trusted.append(endorsed)
        else:
            logger.warning('ignoring un-endorsed / invalid key-rotation bundle for app %r', app_id)
    return _dedupe(trusted)
