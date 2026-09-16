"""SEC-CC-1 runtime unlocker for cryptographically-coupled premium features.

A premium feature ships as an encrypted ``.sealed`` blob (under ``premium/``).
Its plaintext data key is wrapped by the license server under a key derived from
(this host's fingerprint + license_id + feature) and delivered in the license's
``feature_keyring`` (online: via the activate/heartbeat response, cached by the
lifecycle). At runtime we re-derive the wrap key from THIS host, unwrap the data
key, decrypt the blob in memory, and exec it.

So neither patching the verifier nor forging a tier unlocks anything: a forged
payload carries no server-signed wrapped key, a non-entitled tier has no keyring
entry, and a license copied to another machine derives the wrong wrap key.

FAIL-SAFE: any failure raises :class:`FeatureLocked`; callers catch it and treat
the feature as unavailable while the rest of the product keeps running. We NEVER
fall back to plaintext on the customer host.

Dev escape hatch (AGENTS.md invariant #4): loading the un-sealed plaintext is
allowed ONLY when BOTH the ``RSTLIC_DEV_UNSEALED=1`` env var is set AND the
``premium_src/<module>.py`` marker file is present — and that directory is
git-ignored + docker-ignored, so it can never exist in a shipped release. A
customer therefore cannot enable it.
"""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Optional

from rstlic_features import FeatureLocked, load_feature_module

logger = logging.getLogger("rst.feature_unlock")

_SEALED_DIR = Path(__file__).parent / "premium"
_DEV_SRC_DIR = Path(__file__).parent / "premium_src"

# feature id  ->  (sealed blob filename, dev plaintext module filename)
_FEATURES = {
    "detection_rule_copilot": ("detection_rule_copilot.sealed", "detection_rule_core.py"),
    "alert_triage": ("alert_triage.sealed", "alert_triage_core.py"),
    "alert_investigation": ("alert_investigation.sealed", "alert_investigation_core.py"),
    "platform_ops_copilot": ("platform_ops_copilot.sealed", "platform_ops_core.py"),
}

# Cache the unlocked namespace per (feature, license_id, fingerprint) so we only
# pay the AEAD decrypt + exec once. Keyed so a re-activation under a different
# license / host can't serve a stale unlock.
_cache: dict[tuple, dict] = {}


def load_premium(feature: str) -> dict:
    """Unlock + load a sealed premium feature module, returning its namespace.

    Raises :class:`FeatureLocked` when the feature is not entitled, the license
    is bound to another host, no keyring is present (forged/patched payload), or
    the sealed blob is missing.
    """
    spec = _FEATURES.get(feature)
    if spec is None:
        raise FeatureLocked(f"unknown premium feature {feature!r}")
    sealed_name, dev_name = spec

    # Resolve the host binding from the live license state.
    from . import license_state as ls
    license_id = ls.get_license_id()
    keyring = ls.get_feature_keyring()
    fingerprint = _host_fingerprint()

    cache_key = (feature, license_id, fingerprint)
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    # Dev escape hatch takes precedence when armed: a developer's machine may
    # well hold a real (activated) license AND a shipped .sealed blob for some
    # feature, and still needs to run the plaintext it is editing. Both
    # conditions (env var + the git/docker-ignored directory) can only be true
    # on a dev box — see the module docstring.
    if _dev_unsealed_allowed(dev_name):
        return self_dev_load(feature, dev_name)

    if not license_id or not fingerprint:
        if _dev_unsealed_allowed(dev_name):
            return self_dev_load(feature, dev_name)
        raise FeatureLocked(
            f"{feature!r} locked: no active host-bound license on this machine"
        )

    sealed_path = _SEALED_DIR / sealed_name
    if not sealed_path.exists():
        # No ciphertext shipped — try the dev plaintext, else stay locked.
        if _dev_unsealed_allowed(dev_name):
            return self_dev_load(feature, dev_name)
        raise FeatureLocked(f"{feature!r} sealed blob not found at {sealed_path}")

    sealed_blob = sealed_path.read_bytes()
    ns = load_feature_module(
        feature, sealed_blob,
        host_fingerprint=fingerprint,
        license_id=license_id,
        keyring=keyring,
        module_name=f"<rstlic-sealed:{feature}>",
    )
    _cache[cache_key] = ns
    logger.info("premium_feature_unlocked", extra={"feature": feature, "license_id": license_id})
    return ns


def self_dev_load(feature: str, dev_name: str) -> dict:
    """Load the git-ignored plaintext (dev only — see module docstring)."""
    src_path = _DEV_SRC_DIR / dev_name
    logger.warning(
        "premium_feature_dev_unsealed",
        extra={"feature": feature, "path": str(src_path)},
    )
    mod_name = f"_rstlic_dev_{feature}"
    spec = importlib.util.spec_from_file_location(mod_name, src_path)
    if spec is None or spec.loader is None:
        raise FeatureLocked(f"{feature!r} dev source could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return vars(module)


def _dev_unsealed_allowed(dev_name: str) -> bool:
    return (
        os.environ.get("RSTLIC_DEV_UNSEALED") == "1"
        and (_DEV_SRC_DIR / dev_name).exists()
    )


def _host_fingerprint() -> Optional[str]:
    from .server_guid import get_host_fingerprint
    from rstlic_client import RSTLicHardwareUnavailable
    try:
        return get_host_fingerprint()
    except RSTLicHardwareUnavailable:
        return None


def reset_cache() -> None:
    """Drop the unlocked-namespace cache (used by tests / after re-activation)."""
    _cache.clear()
