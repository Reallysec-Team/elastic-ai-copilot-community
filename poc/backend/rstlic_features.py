"""Cryptographically-coupled feature unlocking for the RST License SDK (SEC-CC-1).

The verifier proves a license is *valid*; the app then branches on
``payload['features']`` to gate premium behaviour. That branch is a plain
``if`` — patch the compiled verifier to return a forged ``enterprise`` payload
(or just flip the feature list) and every gate opens. The signature, host
binding and CRL are all bypassed by that one edit.

This module closes that by making premium features *unreadable* without a key
that only a genuine, correctly-bound license carries:

* Each premium feature's real code/data is encrypted at BUILD time under a
  random per-feature **data key** (DK) and shipped as ciphertext
  (:func:`seal_feature`). The plaintext never ships.
* The license server wraps DK under a key DERIVED FROM (host fingerprint +
  license_id + feature) and delivers the wrapped DKs as a ``feature_keyring``
  in the signed payload — but ONLY for the features that license's tier
  entitles.
* At runtime the app re-derives the wrap key from THIS host's fingerprint,
  unwraps DK (:func:`unlock_data_key`) and decrypts the feature
  (:func:`open_feature`).

So "skip the check" no longer unlocks anything:

* a forged payload doesn't contain the server-signed wrapped DKs (minting them
  needs the private key);
* a standard-tier license simply has no keyring entry for an enterprise
  feature — nothing to unwrap;
* a license copied to another machine derives the wrong wrap key (the
  fingerprint differs) and the unwrap fails.

The KDF and blob format here MUST byte-match the server
(``server/services/feature_keys.py``) — there is a round-trip parity test.

Depends only on ``cryptography`` + stdlib so it can be vendored standalone.
"""
from __future__ import annotations

import base64
import os
from typing import Optional, Union

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
except ImportError:  # pragma: no cover - exercised only on bare runtimes
    import sys
    _vendor_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendor')
    if _vendor_dir not in sys.path:
        sys.path.insert(0, _vendor_dir)
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# --- protocol constants (MUST match server/services/feature_keys.py) --------
_DK_LEN = 32                         # AES-256 data key
_NONCE_LEN = 12                      # AES-GCM nonce
_WRAP_INFO = b'rstlic-feat-v1:'      # HKDF info prefix for the DK wrap key
_FEATURE_AAD = b'rstlic-feature-v1'  # AAD binding for a sealed feature blob

BytesLike = Union[bytes, bytearray]


class FeatureLocked(Exception):
    """A premium feature could not be unlocked on this host with this license.

    Callers should treat this as "feature unavailable" and keep the app
    running (fail-safe) rather than crashing — the feature stays locked, the
    rest of the product works.
    """


# ---------------------------------------------------------------------------
# Key derivation (parity-critical with the server)
# ---------------------------------------------------------------------------
def derive_feature_key(host_fingerprint: str, license_id: str, feature: str) -> bytes:
    """Derive the 32-byte key that wraps ``feature``'s data key for this host.

    ``HKDF-SHA256(ikm=fingerprint, salt=license_id, info='rstlic-feat-v1:'+feature)``.
    Binding to the fingerprint is what makes a copied license useless; binding
    to license_id stops one license's keyring vouching for another's.
    """
    if not host_fingerprint or not license_id or not feature:
        raise FeatureLocked('missing fingerprint / license_id / feature for key derivation')
    return HKDF(
        algorithm=hashes.SHA256(),
        length=_DK_LEN,
        salt=license_id.encode('utf-8'),
        info=_WRAP_INFO + feature.encode('utf-8'),
    ).derive(host_fingerprint.encode('utf-8'))


# ---------------------------------------------------------------------------
# Data-key unwrap (runtime, client side)
# ---------------------------------------------------------------------------
def unlock_data_key(feature: str, *,
                    host_fingerprint: str,
                    license_id: str,
                    keyring: Optional[dict]) -> bytes:
    """Return the data key for ``feature`` by unwrapping the license's keyring
    entry with a key derived from THIS host. Raises :class:`FeatureLocked` when
    the feature isn't entitled (no keyring entry), the keyring is missing, or
    the wrap key is wrong (license bound to another host / forged).
    """
    if not keyring or not isinstance(keyring, dict):
        raise FeatureLocked(f'no feature keyring on this license; {feature!r} is locked')
    wrapped_b64 = keyring.get(feature)
    if not wrapped_b64:
        raise FeatureLocked(f'feature {feature!r} is not entitled by this license')
    try:
        blob = base64.b64decode(wrapped_b64)
    except Exception as e:  # noqa: BLE001
        raise FeatureLocked(f'feature {feature!r} keyring entry is malformed: {e}')
    if len(blob) < _NONCE_LEN + 16:
        raise FeatureLocked(f'feature {feature!r} keyring entry is too short')
    wrap_key = derive_feature_key(host_fingerprint, license_id, feature)
    try:
        dk = AESGCM(wrap_key).decrypt(blob[:_NONCE_LEN], blob[_NONCE_LEN:],
                                      feature.encode('utf-8'))
    except Exception:  # noqa: BLE001 — wrong host / tampered => locked
        raise FeatureLocked(
            f'feature {feature!r} could not be unlocked on this machine — the '
            'license is bound to a different host or has been tampered with'
        )
    if len(dk) != _DK_LEN:
        raise FeatureLocked(f'feature {feature!r} data key has unexpected length')
    return dk


# ---------------------------------------------------------------------------
# Sealed-feature blob (encrypt at build, decrypt at runtime)
# ---------------------------------------------------------------------------
def seal_feature(plaintext: BytesLike, data_key: bytes) -> bytes:
    """Encrypt a premium feature's code/data under its data key (BUILD time).
    Returns ``nonce || ciphertext`` — ship this, never the plaintext."""
    if len(data_key) != _DK_LEN:
        raise ValueError(f'data_key must be {_DK_LEN} bytes')
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(data_key).encrypt(nonce, bytes(plaintext), _FEATURE_AAD)
    return nonce + ct


def open_feature(blob: BytesLike, data_key: bytes) -> bytes:
    """Decrypt a :func:`seal_feature` blob with its data key (RUNTIME). Raises
    :class:`FeatureLocked` if the key is wrong or the blob was tampered with."""
    blob = bytes(blob)
    if len(blob) < _NONCE_LEN + 16:
        raise FeatureLocked('sealed feature blob is too short')
    try:
        return AESGCM(data_key).decrypt(blob[:_NONCE_LEN], blob[_NONCE_LEN:], _FEATURE_AAD)
    except Exception:  # noqa: BLE001
        raise FeatureLocked('sealed feature could not be decrypted (wrong key or tampered)')


def unlock_and_open(feature: str, sealed_blob: BytesLike, *,
                    host_fingerprint: str,
                    license_id: str,
                    keyring: Optional[dict]) -> bytes:
    """Convenience: unwrap the data key for ``feature`` then decrypt
    ``sealed_blob``. Raises :class:`FeatureLocked` on any failure."""
    dk = unlock_data_key(feature, host_fingerprint=host_fingerprint,
                         license_id=license_id, keyring=keyring)
    return open_feature(sealed_blob, dk)


def load_feature_module(feature: str, sealed_blob: BytesLike, *,
                        host_fingerprint: str,
                        license_id: str,
                        keyring: Optional[dict],
                        module_name: str = '<rstlic-feature>',
                        namespace: Optional[dict] = None) -> dict:
    """Unlock + decrypt a sealed Python feature module and exec it in a fresh
    namespace, returned to the caller. Raises :class:`FeatureLocked` if the
    feature can't be unlocked; lets a SyntaxError/runtime error propagate.

    The decrypted source is exec'd from memory and never written to disk.
    """
    source = unlock_and_open(feature, sealed_blob, host_fingerprint=host_fingerprint,
                             license_id=license_id, keyring=keyring)
    ns = namespace if namespace is not None else {'__name__': module_name}
    exec(compile(source, module_name, 'exec'), ns)
    return ns
