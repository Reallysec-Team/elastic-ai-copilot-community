"""P3 — gateway release downloader + staging.

Mints REAL RSA-PSS manifests with an ephemeral key and drives the actual
download/verify/stage path with injected fake fetchers. Focus: the fail-closed
invariant (a bad artifact never touches the current pointer), the disk guard,
and the updater-version gate.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
import types
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_POC = Path(__file__).resolve().parent.parent.parent  # .../poc
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import release_store  # noqa: E402

IMG = b"IMAGE-TARBALL-BYTES-v2"
UPD = b"UPDATER-SCRIPT-BYTES-v2"
IMG_SHA = hashlib.sha256(IMG).hexdigest()
UPD_SHA = hashlib.sha256(UPD).hexdigest()


def _sign(priv, manifest: dict) -> str:
    pj = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    pb = base64.b64encode(pj.encode()).decode()
    sig = priv.sign(pb.encode(), padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
    return pb + "." + base64.b64encode(sig).decode()


def _manifest(version="2.0.0", min_updater=0, app_id="rst_elastic_ai_copilot"):
    return {
        "app_id": app_id, "release_version": version,
        "min_updater_version": min_updater, "created_at": "2026-07-11T00:00:00Z",
        "artifacts": [
            {"kind": "image", "sha256": IMG_SHA, "size": len(IMG)},
            {"kind": "updater", "sha256": UPD_SHA, "size": len(UPD)},
        ],
    }


def _release(token, corrupt=False):
    """The heartbeat 'release' payload with per-artifact download URLs."""
    return {
        "version": "2.0.0", "manifest_url": "M://manifest",
        "artifacts": [
            {"kind": "image", "sha256": IMG_SHA, "size": len(IMG), "url": "A://img"},
            {"kind": "updater", "sha256": UPD_SHA, "size": len(UPD),
             "url": "A://upd" + ("-bad" if corrupt else "")},
        ],
    }


@pytest.fixture
def priv(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = tmp_path / "content_pub.pem"
    pub.write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    monkeypatch.setenv("RST_CONTENT_PUBLIC_KEY_PATH", str(pub))
    monkeypatch.delenv("RST_CONTENT_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("RST_RELEASE_DIR", str(tmp_path / "release"))
    monkeypatch.setattr(release_store, "APP_VERSION", "1.1.0")
    monkeypatch.setattr(release_store, "UPDATER_VERSION", 1)
    return key


def _fetchers(token, url_bytes):
    def fetch_text(url):
        assert url == "M://manifest"
        return token
    def download_to(url, dest):
        data = url_bytes[url]
        dest.write_bytes(data)
        return hashlib.sha256(data).hexdigest()
    return fetch_text, download_to


def test_happy_stage(priv):
    token = _sign(priv, _manifest())
    ft, dt = _fetchers(token, {"A://img": IMG, "A://upd": UPD})
    st = release_store.download_and_stage(_release(token), fetch_text=ft, download_to=dt)
    assert st["staged_version"] == "2.0.0"
    assert {a["sha256"] for a in st["artifacts"]} == {IMG_SHA, UPD_SHA}
    staging = release_store._staging_dir()
    assert (staging / IMG_SHA).read_bytes() == IMG
    assert not list(staging.glob("*.part"))  # nothing left partial


def test_sha_mismatch_is_fail_closed(priv):
    """Core invariant: a corrupted artifact wipes staging and leaves the
    current pointer untouched."""
    token = _sign(priv, _manifest())
    ft, dt = _fetchers(token, {"A://img": IMG, "A://upd-bad": b"CORRUPTED"})
    with pytest.raises(release_store.ReleaseError):
        release_store.download_and_stage(_release(token, corrupt=True),
                                         fetch_text=ft, download_to=dt)
    assert not release_store._pointer_file().exists()      # current untouched
    assert not list(release_store._staging_dir().iterdir())  # staging wiped


def test_mismatch_preserves_prior_staged(priv):
    """A failed v-next must not clobber an already-staged good release."""
    token = _sign(priv, _manifest())
    ft, dt = _fetchers(token, {"A://img": IMG, "A://upd": UPD})
    release_store.download_and_stage(_release(token), fetch_text=ft, download_to=dt)
    assert release_store.status()["staged_version"] == "2.0.0"
    # now a corrupt attempt
    ft2, dt2 = _fetchers(token, {"A://img": IMG, "A://upd-bad": b"XXX"})
    with pytest.raises(release_store.ReleaseError):
        release_store.download_and_stage(_release(token, corrupt=True),
                                         fetch_text=ft2, download_to=dt2)
    assert release_store.status()["staged_version"] == "2.0.0"  # unchanged


def test_disk_insufficient_refused(priv, monkeypatch):
    token = _sign(priv, _manifest())
    ft, dt = _fetchers(token, {"A://img": IMG, "A://upd": UPD})
    monkeypatch.setattr(release_store.shutil, "disk_usage",
                        lambda p: types.SimpleNamespace(total=1, used=1, free=10))
    with pytest.raises(release_store.ReleaseError, match="insufficient disk"):
        release_store.download_and_stage(_release(token), fetch_text=ft, download_to=dt)
    assert not release_store._pointer_file().exists()


def test_updater_too_old_refused(priv):
    token = _sign(priv, _manifest(min_updater=99))
    ft, dt = _fetchers(token, {"A://img": IMG, "A://upd": UPD})
    with pytest.raises(release_store.ReleaseError, match="updater version"):
        release_store.download_and_stage(_release(token), fetch_text=ft, download_to=dt)


def test_not_newer_refused(priv):
    token = _sign(priv, _manifest(version="1.0.0"))
    rel = _release(token); rel["version"] = "1.0.0"
    ft, dt = _fetchers(token, {"A://img": IMG, "A://upd": UPD})
    with pytest.raises(release_store.ReleaseError, match="not newer"):
        release_store.download_and_stage(rel, fetch_text=ft, download_to=dt)


def test_wrong_app_refused(priv):
    token = _sign(priv, _manifest(app_id="other_app"))
    ft, dt = _fetchers(token, {"A://img": IMG, "A://upd": UPD})
    with pytest.raises(release_store.ReleaseError, match="app_id"):
        release_store.download_and_stage(_release(token), fetch_text=ft, download_to=dt)


def test_on_verify_failed_fires_on_sha_mismatch(priv):
    token = _sign(priv, _manifest())
    ft, dt = _fetchers(token, {"A://img": IMG, "A://upd-bad": b"CORRUPTED"})
    reported = []
    with pytest.raises(release_store.ManifestVerifyError):
        release_store.download_and_stage(
            _release(token, corrupt=True), fetch_text=ft, download_to=dt,
            on_verify_failed=lambda r: reported.append(r))
    assert len(reported) == 1 and "sha256 mismatch" in reported[0]


def test_on_verify_failed_not_fired_on_policy_error(priv):
    # updater-too-old is a policy refusal, NOT an intrusion signal → no report
    token = _sign(priv, _manifest(min_updater=99))
    ft, dt = _fetchers(token, {"A://img": IMG, "A://upd": UPD})
    reported = []
    with pytest.raises(release_store.ReleaseError):
        release_store.download_and_stage(
            _release(token), fetch_text=ft, download_to=dt,
            on_verify_failed=lambda r: reported.append(r))
    assert reported == []


def test_forged_manifest_rejected(priv, tmp_path):
    """A manifest signed by a different key must not verify."""
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _sign(other, _manifest())
    ft, dt = _fetchers(token, {"A://img": IMG, "A://upd": UPD})
    with pytest.raises(release_store.ReleaseError):
        release_store.download_and_stage(_release(token), fetch_text=ft, download_to=dt)
