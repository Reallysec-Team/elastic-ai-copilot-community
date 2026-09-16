"""License SDK test net — verifier definition-of-done + SEC-CC-1 + offline grace.

Mirrors RST Splunk AI Copilot's tests/test_license_sec_cc1.py for this product.
It mints REAL RSA-PSS-signed tokens with an ephemeral keypair (no license server
needed) and runs them through the actual vendored SDK verifier + feature-unlock
primitives, plus the product's own offline activation / grace logic.

Covers AGENTS.md "definition of done":
  * a valid token passes; tampered / expired / wrong-product / wrong-key rejected
  * SEC-CC-1: a sealed feature opens ONLY on the bound host with the right
    license keyring, and stays locked on the wrong host or with no keyring
    (the "patched verifier / forged payload" case)
  * offline grace: in-grace vs past-grace (online), and an offline/air-gapped
    token bound to this host vs another host.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

# The vendored SDK is imported flat (see backend/__init__.py); the tests add the
# backend dir to sys.path so they can import the SDK without importing a handler.
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402

import rstlic_verifier as V  # noqa: E402
import rstlic_features as F  # noqa: E402
from rstlic_storage import MemoryStorage  # noqa: E402
from rstlic_lifecycle import LicenseLifecycle, StorageKeys  # noqa: E402

APP_ID = "rst_elastic_ai_copilot"
SERVER_GUID = "UNBOUND"
FP = "a" * 64
FEATURE = "detection_rule_copilot"


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return key, pub_pem


def _mint(priv, *, product=APP_ID, server_guid=SERVER_GUID, days=30,
          features=None, license_type="enterprise", extra=None):
    """Mint a token byte-compatible with the server signer: RSA-PSS over the
    base64 payload string. ``extra`` merges offline / keyring fields."""
    now = datetime.now(timezone.utc)
    payload = {
        "license_id": "LIC-TEST-0001",
        "product": product,
        "app_id": product,
        "license_type": license_type,
        "issue_date": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "expiry_date": (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "server_guid": server_guid,
        "max_nodes": -1,
        "features": features if features is not None else ["*"],
        "version": 2,
    }
    if extra:
        payload.update(extra)
    payload_b64 = base64.b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii")
    sig = priv.sign(
        payload_b64.encode("ascii"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return payload_b64 + "." + base64.b64encode(sig).decode("ascii")


# --- verifier definition-of-done -------------------------------------------

def test_valid_token_passes(keypair):
    priv, pub = keypair
    v = V.LicenseVerifier(public_key_pem=pub, expected_product=APP_ID)
    data = v.validate_full(_mint(priv), server_guid=SERVER_GUID)
    assert data["license_id"] == "LIC-TEST-0001"
    assert data["product"] == APP_ID


def test_tampered_payload_rejected(keypair):
    priv, pub = keypair
    token = _mint(priv)
    head, sig = token.split(".")
    raw = bytearray(base64.b64decode(head))
    raw[10] ^= 0x01  # flip one byte of the signed payload
    tampered = base64.b64encode(bytes(raw)).decode("ascii") + "." + sig
    v = V.LicenseVerifier(public_key_pem=pub, expected_product=APP_ID)
    with pytest.raises(V.LicenseError):
        v.validate_full(tampered, server_guid=SERVER_GUID)


def test_expired_token_rejected(keypair):
    priv, pub = keypair
    v = V.LicenseVerifier(public_key_pem=pub, expected_product=APP_ID)
    with pytest.raises(V.LicenseError):
        v.validate_full(_mint(priv, days=-1), server_guid=SERVER_GUID)


def test_wrong_product_rejected(keypair):
    priv, pub = keypair
    v = V.LicenseVerifier(public_key_pem=pub, expected_product=APP_ID)
    with pytest.raises(V.LicenseError):
        v.validate_full(_mint(priv, product="some-other-app"), server_guid=SERVER_GUID)


def test_wrong_key_rejected(keypair):
    priv, _pub = keypair
    other = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    other_pub = other.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    v = V.LicenseVerifier(public_key_pem=other_pub, expected_product=APP_ID)
    with pytest.raises(V.LicenseError):
        v.validate_full(_mint(priv), server_guid=SERVER_GUID)


# --- SEC-CC-1: cryptographic feature coupling -------------------------------

def _wrap_keyring(dk, fingerprint, license_id, feature):
    """Mirror the server's feature_keys.wrap_keyring using the SDK's own KDF
    (parity is tested server-side). Builds a keyring with no license server."""
    wrap_key = F.derive_feature_key(fingerprint, license_id, feature)
    nonce = os.urandom(12)
    ct = AESGCM(wrap_key).encrypt(nonce, dk, feature.encode("utf-8"))
    return base64.b64encode(nonce + ct).decode("ascii")


def test_sealed_feature_unlocks_on_bound_host():
    dk = os.urandom(32)
    sealed = F.seal_feature(b'def run():\n    return "PREMIUM-DETECTION-OK"\n', dk)
    keyring = {FEATURE: _wrap_keyring(dk, FP, "LIC-TEST-0001", FEATURE)}
    ns = F.load_feature_module(FEATURE, sealed, host_fingerprint=FP,
                               license_id="LIC-TEST-0001", keyring=keyring)
    assert ns["run"]() == "PREMIUM-DETECTION-OK"


def test_sealed_feature_locked_on_wrong_host():
    dk = os.urandom(32)
    sealed = F.seal_feature(b'def run():\n    return 1\n', dk)
    keyring = {FEATURE: _wrap_keyring(dk, FP, "LIC-TEST-0001", FEATURE)}
    with pytest.raises(F.FeatureLocked):
        F.unlock_and_open(FEATURE, sealed, host_fingerprint="b" * 64,
                          license_id="LIC-TEST-0001", keyring=keyring)


def test_sealed_feature_locked_without_keyring():
    """The 'patched verifier returns a forged payload' case: no server keyring,
    so there is no wrapped data key to derive — the feature cannot open."""
    dk = os.urandom(32)
    sealed = F.seal_feature(b'def run():\n    return 1\n', dk)
    with pytest.raises(F.FeatureLocked):
        F.unlock_and_open(FEATURE, sealed, host_fingerprint=FP,
                          license_id="LIC-TEST-0001", keyring=None)


def test_sealed_feature_not_entitled_when_absent_from_keyring():
    dk = os.urandom(32)
    sealed = F.seal_feature(b'def run():\n    return 1\n', dk)
    keyring = {"some_other_feature": _wrap_keyring(dk, FP, "LIC-TEST-0001", "some_other_feature")}
    with pytest.raises(F.FeatureLocked):
        F.unlock_and_open(FEATURE, sealed, host_fingerprint=FP,
                          license_id="LIC-TEST-0001", keyring=keyring)


def test_sealed_detection_core_unlocks_and_normalizes():
    """End-to-end with the REAL premium detection-rule engine source: seal it,
    wrap its DK to this host, unlock + exec, and confirm normalize() runs."""
    src_path = os.path.join(_BACKEND, "premium_src", "detection_rule_core.py")
    if not os.path.exists(src_path):
        pytest.skip("premium_src/detection_rule_core.py not present (build-vault input)")
    with open(src_path, "rb") as f:
        plaintext = f.read()
    dk = os.urandom(32)
    sealed = F.seal_feature(plaintext, dk)
    keyring = {FEATURE: _wrap_keyring(dk, FP, "LIC-TEST-0001", FEATURE)}
    ns = F.load_feature_module(FEATURE, sealed, host_fingerprint=FP,
                               license_id="LIC-TEST-0001", keyring=keyring)
    out = ns["normalize"]({"rule": None, "explanation": "x"}, "logs-*")
    assert out["rule"] is None and out["rule_type"] is None


# --- offline grace + revocation (lifecycle) ---------------------------------

def _life_with_contact(days_ago: int, *, revoked: bool = False, lid="LIC-TEST-0001"):
    store = MemoryStorage()
    keys = StorageKeys()
    last = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.set(keys.last_ok, last)
    store.set(keys.state_lid, lid)
    if revoked:
        store.set(keys.revoked, "1")
    # client=None: read-only status methods only touch storage.
    return LicenseLifecycle(client=None, storage=store, offline_grace_days=7, keys=keys)


def test_offline_grace_within_window():
    life = _life_with_contact(days_ago=2)
    assert life.in_offline_grace("LIC-TEST-0001") is True
    assert life.is_revoked("LIC-TEST-0001") is False


def test_offline_grace_past_window():
    life = _life_with_contact(days_ago=10)
    assert life.in_offline_grace("LIC-TEST-0001") is False


def test_revoked_flag_blocks():
    life = _life_with_contact(days_ago=1, revoked=True)
    assert life.is_revoked("LIC-TEST-0001") is True


def test_foreign_license_gets_no_grace():
    """A successful contact recorded for a DIFFERENT license must not vouch for
    the one now installed (max_nodes bypass guard)."""
    life = _life_with_contact(days_ago=1, lid="LIC-OTHER")
    assert life.in_offline_grace("LIC-TEST-0001") is False


# --- offline (air-gapped) host binding --------------------------------------

def test_offline_token_bound_to_this_host_validates(keypair):
    priv, pub = keypair
    token = _mint(priv, extra={"mode": "offline", "bound_fingerprint": FP})
    v = V.LicenseVerifier(public_key_pem=pub, expected_product=APP_ID)
    data = v.validate_offline(token, host_fingerprint=FP, expected_product=APP_ID)
    assert data["mode"] == "offline"


def test_offline_token_rejected_on_other_host(keypair):
    priv, pub = keypair
    token = _mint(priv, extra={"mode": "offline", "bound_fingerprint": FP})
    v = V.LicenseVerifier(public_key_pem=pub, expected_product=APP_ID)
    with pytest.raises(V.LicenseError):
        v.validate_offline(token, host_fingerprint="c" * 64, expected_product=APP_ID)


def test_offline_keyring_unlocks_only_on_bound_host(keypair):
    """An offline token's embedded keyring unlocks the sealed feature on the
    bound host, and not on another."""
    dk = os.urandom(32)
    sealed = F.seal_feature(b'def run():\n    return "OFFLINE-OK"\n', dk)
    keyring = {FEATURE: _wrap_keyring(dk, FP, "LIC-TEST-0001", FEATURE)}
    ns = F.load_feature_module(FEATURE, sealed, host_fingerprint=FP,
                               license_id="LIC-TEST-0001", keyring=keyring)
    assert ns["run"]() == "OFFLINE-OK"
    with pytest.raises(F.FeatureLocked):
        F.unlock_and_open(FEATURE, sealed, host_fingerprint="d" * 64,
                          license_id="LIC-TEST-0001", keyring=keyring)


# --- fingerprint stability sync-guard (RST-LOCAL PATCH) ---------------------

def test_fingerprint_ignores_volatile_kernel_and_cpu(monkeypatch):
    """Sync guard: the hardware fingerprint must NOT change when the kernel
    release or vCPU count changes — otherwise a routine `apt upgrade` (kernel
    bump) or a VM resize would silently invalidate an activated license and lock
    the customer out. This is the whole point of dropping platform.release() /
    os.cpu_count() from the blend. If a future SDK re-sync from upstream
    reintroduces either field, THIS test fails loudly instead of shipping the
    license-bricking regression again.
    """
    import os as _os
    import platform as _platform

    import rstlic_client as rc

    # Pin the stable hardware roots so the test is deterministic on any host
    # (CI containers may lack a real machine-id / MAC).
    monkeypatch.setattr(rc, "_platform_machine_id", lambda: "stable-machine-id")
    monkeypatch.setattr(rc, "_primary_mac", lambda: "aabbccddeeff")

    monkeypatch.setattr(_platform, "release", lambda: "5.15.0-91-generic")
    monkeypatch.setattr(_os, "cpu_count", lambda: 4)
    fp1 = rc.RSTLicClient.fingerprint(server_guid="g", app_id=APP_ID)

    # Same machine, kernel patched + VM resized: fingerprint must be identical.
    monkeypatch.setattr(_platform, "release", lambda: "6.8.0-40-generic")
    monkeypatch.setattr(_os, "cpu_count", lambda: 64)
    fp2 = rc.RSTLicClient.fingerprint(server_guid="g", app_id=APP_ID)

    assert fp1 == fp2, "fingerprint must not depend on kernel release / vCPU count"


# --- HIGH-1: session token must bind to BOTH host and license_id ------------

def _mint_session(priv, *, license_id, fingerprint=FP, app_id=APP_ID, days=30):
    """Mint a SEC-AC-1 session token (kind='session', host+license bound),
    byte-compatible with the server signer, so the HIGH-1 binding check can be
    exercised with no license server."""
    now = datetime.now(timezone.utc)
    payload = {
        "kind": "session",
        "license_id": license_id,
        "app_id": app_id,
        "fingerprint": fingerprint,
        "exp": (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    }
    payload_b64 = base64.b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii")
    sig = priv.sign(
        payload_b64.encode("ascii"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return payload_b64 + "." + base64.b64encode(sig).decode("ascii")


def test_session_token_accepts_matching_host_and_license(keypair):
    priv, pub = keypair
    tok = _mint_session(priv, license_id="LIC-TEST-0001")
    data = V.verify_session_token(tok, pub, FP, expected_license_id="LIC-TEST-0001")
    assert data["license_id"] == "LIC-TEST-0001"


def test_session_token_rejects_foreign_license(keypair):
    """HIGH-1: a cheap/trial license's host-bound session token must not vouch
    for a costlier license_token pasted on the same host (max_nodes bypass)."""
    priv, pub = keypair
    tok = _mint_session(priv, license_id="LIC-TRIAL-CHEAP")
    with pytest.raises(V.LicenseError):
        V.verify_session_token(tok, pub, FP, expected_license_id="LIC-TEST-0001")


def test_session_token_rejects_wrong_host(keypair):
    """SEC-AC-1: a session token minted for another machine's fingerprint must
    not validate here even when the license_id matches (copied-license)."""
    priv, pub = keypair
    tok = _mint_session(priv, license_id="LIC-TEST-0001", fingerprint="b" * 64)
    with pytest.raises(V.LicenseError):
        V.verify_session_token(tok, pub, FP, expected_license_id="LIC-TEST-0001")


# --- HIGH-3: activation seeds the heartbeat clock ---------------------------

class _StubActivateClient:
    """Minimal RSTLicClient stand-in: returns a server-shaped activate response
    and a deterministic fingerprint, so the lifecycle's activate() can run with
    no network."""
    server_guid = SERVER_GUID
    app_id = APP_ID

    def fingerprint(self, server_guid, app_id):
        return FP

    def activate(self, *, license_id, host_fingerprint, splunk_version=""):
        return {"token": "srv-token", "session_token": "sess",
                "session_secret": "s3cr3t"}


def test_activation_seeds_heartbeat_clock():
    """HIGH-3: a successful activation is a successful phone-home, so last_ok
    must be seeded — otherwise a server that goes unreachable right after
    activation leaves the HEARTBEAT_LOST lockout unable to ever fire."""
    store = MemoryStorage()
    keys = StorageKeys()
    life = LicenseLifecycle(client=_StubActivateClient(), storage=store, keys=keys)
    assert not store.get(keys.last_ok)  # precondition: clock unset
    life.activate(license_id="LIC-TEST-0001")
    assert store.get(keys.last_ok), "activation must seed last_ok (HIGH-3)"


# ───────────── the product-level claim: patching the gate unlocks nothing ─────────────

@pytest.mark.parametrize("feature,call", [
    ("alert_triage", "triage"),
    ("alert_investigation", "investigate"),
    ("platform_ops_copilot", "platform"),
    ("detection_rule_copilot", "detection_rule"),
])
def test_every_paid_engine_stays_locked_when_the_license_check_is_patched(monkeypatch, feature, call):
    """开源之后最先被人改的那一行是 `feature_allowed()`。这条证明改了也没用：
    四个付费能力的引擎都是密封件，判定放行只是让请求走到 `load_premium()`，
    而那里缺的是密钥——没有 keyring 就没有东西可解，`return True` 变不出密钥。

    关掉开发逃生舱（否则本机会直接读明文），不给许可、不给 keyring，然后把
    判定打成永远放行。每一路都必须在花掉任何 ES / LLM 调用之前抛 FeatureLocked。
    """
    import asyncio
    from backend import license_state as ls, feature_unlock, prompts

    monkeypatch.setenv("RSTLIC_DEV_UNSEALED", "0")
    monkeypatch.setattr(ls, "feature_allowed", lambda _f: True)
    monkeypatch.setattr(ls, "has_feature", lambda _f: True)
    monkeypatch.setattr(ls, "get_license_id", lambda: None)
    monkeypatch.setattr(ls, "get_feature_keyring", lambda: None)
    feature_unlock._cache.clear()

    def boom(*a, **k):
        raise AssertionError("reached ES/LLM — the engine must lock BEFORE any spend")

    if call == "triage":
        from backend import triage
        monkeypatch.setattr(triage, "get_es", boom)
        with pytest.raises(F.FeatureLocked):
            asyncio.run(triage.triage_alerts([{"_id": "1", "_source": {"rule": {"id": "x"}}}]))
    elif call == "investigate":
        from backend import agentic_investigate
        with pytest.raises(F.FeatureLocked):
            asyncio.run(agentic_investigate._investigate_loop({"a": 1}, "idx", 60, 1, None))
    elif call == "platform":
        with pytest.raises(F.FeatureLocked):
            prompts.platform_interpret_system_prompt()
    else:
        with pytest.raises(F.FeatureLocked):
            prompts.detection_rule_system_prompt()
