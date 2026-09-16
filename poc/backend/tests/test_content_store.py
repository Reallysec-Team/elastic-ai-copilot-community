"""Tests for signed content packs (online prompt delivery).

Mints REAL RSA-PSS packs with an ephemeral keypair (no license server / ES
needed) and runs them through the actual content_store verify/apply/rollback —
the security-critical path: signature, tamper-reject, wrong-app, min-app gate,
anti-rollback, and the embedded-defaults floor.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_POC = Path(__file__).resolve().parent.parent.parent  # .../poc
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import content_store  # noqa: E402
from backend.rstlic_verifier import LicenseError  # noqa: E402


def _sign(priv, pack: dict) -> str:
    payload_json = json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload_b64 = base64.b64encode(payload_json.encode("utf-8")).decode("ascii")
    sig = priv.sign(
        payload_b64.encode("ascii"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return payload_b64 + "." + base64.b64encode(sig).decode("ascii")


def _pack(version="2026-07-01.1", body="OVERRIDE", app_id="rst_elastic_ai_copilot", min_app="1.1.0"):
    return {
        "app_id": app_id,
        "pack_version": version,
        "min_app_version": min_app,
        "created_at": "2026-07-01T00:00:00Z",
        "assets": {"prompt.nl2dsl.system": {"kind": "prompt", "body": body}},
    }


@pytest.fixture
def priv(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = tmp_path / "content_pub.pem"
    pub.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    monkeypatch.setenv("RST_CONTENT_PUBLIC_KEY_PATH", str(pub))
    monkeypatch.setenv("RST_LICENSE_PUBLIC_KEY_PATH", str(pub))  # fallback = our key too
    monkeypatch.delenv("RST_CONTENT_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("RST_CONTENT_DIR", str(tmp_path / "content"))
    content_store.reload()
    return key


def test_defaults_floor_when_no_pack(priv):
    assert content_store.active_version() is None
    assert content_store.get("prompt.nl2dsl.system", "DEFAULT") == "DEFAULT"


def test_apply_signed_pack_overrides(priv):
    st = content_store.apply(_sign(priv, _pack(body="HELLO")), actor="t")
    assert st["active_version"] == "2026-07-01.1"
    assert content_store.get("prompt.nl2dsl.system", "DEFAULT") == "HELLO"
    assert content_store.get("prompt.unknown", "DEFAULT") == "DEFAULT"  # missing asset → default


def test_active_sha_matches_server_etag(priv):
    """active_sha() must equal sha256(token) so it matches the server's
    content_packs.sha256 (the online-update dedupe etag). None when no pack."""
    import hashlib

    assert content_store.active_sha() is None
    token = _sign(priv, _pack(body="HELLO"))
    content_store.apply(token, actor="t")
    assert content_store.active_sha() == hashlib.sha256(token.encode("utf-8")).hexdigest()


def test_tampered_pack_rejected(priv):
    token = _sign(priv, _pack())
    tampered = token[:-4] + ("AAAA" if token[-4:] != "AAAA" else "BBBB")
    with pytest.raises(LicenseError):
        content_store.verify_pack_token(tampered)


def test_unsigned_garbage_rejected(priv):
    with pytest.raises(LicenseError):
        content_store.verify_pack_token("not-a-token")


def test_wrong_app_rejected(priv):
    with pytest.raises(LicenseError):
        content_store.verify_pack_token(_sign(priv, _pack(app_id="other_app")))


def test_min_app_version_gate(priv):
    with pytest.raises(LicenseError):
        content_store.verify_pack_token(_sign(priv, _pack(min_app="99.0.0")))


def test_anti_rollback(priv):
    content_store.apply(_sign(priv, _pack(version="2026-07-02.1")), actor="t")
    with pytest.raises(LicenseError):
        content_store.apply(_sign(priv, _pack(version="2026-07-01.1")), actor="t")


def test_rollback_to_archived(priv):
    content_store.apply(_sign(priv, _pack(version="2026-07-01.1", body="V1")), actor="t")
    content_store.apply(_sign(priv, _pack(version="2026-07-02.1", body="V2")), actor="t")
    assert content_store.get("prompt.nl2dsl.system", "D") == "V2"
    content_store.rollback("2026-07-01.1", actor="t")
    assert content_store.active_version() == "2026-07-01.1"
    assert content_store.get("prompt.nl2dsl.system", "D") == "V1"
