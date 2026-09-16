"""API-layer tests for /api/state + /api/admin/content via FastAPI TestClient.

Runs the real app (demo mode: no shared secret → endpoints open, license
unactivated). The validation / auth / routing paths need no ES; the CRUD
round-trip does, so it's skipped when ES isn't reachable (it runs in CI, which
provisions ES, and locally when ES is up).
"""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent  # .../poc
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

# Demo mode (open) + no license BEFORE importing the app.
os.environ.pop("RST_GATEWAY_SHARED_SECRET", None)
os.environ.pop("RST_ADMIN_TOKEN", None)

_ES_URL = os.environ.get("ES_URL", "http://127.0.0.1:9200")


def _es_up() -> bool:
    try:
        urllib.request.urlopen(_ES_URL, timeout=2)
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as c:
        yield c


def test_unknown_state_kind_rejected(client):
    # _check_kind runs before any ES access → 400 without needing ES.
    assert client.get("/api/state/evil").status_code == 400
    assert client.put("/api/state/evil/x", json="v").status_code == 400


def test_content_import_bad_token_rejected(client):
    # Fail-closed signature verification → 400 (admin is open in demo mode).
    r = client.post("/api/admin/content/import", json={"token": "garbage"})
    assert r.status_code == 400


def test_content_status_ok(client):
    r = client.get("/api/admin/content/status")
    assert r.status_code == 200
    assert "active_version" in r.json()


@pytest.mark.skipif(not _es_up(), reason="needs Elasticsearch")
def test_state_roundtrip(client):
    # pref is a personal kind → owner _shared without SSO.
    assert client.put("/api/state/pref/ui_test", json={"k": 1}).json()["ok"] is True
    assert client.get("/api/state/pref/ui_test").json()["value"] == {"k": 1}
    keys = [it["key"] for it in client.get("/api/state/pref").json()["items"]]
    assert "ui_test" in keys
    assert client.delete("/api/state/pref/ui_test").json()["ok"] is True
    assert client.get("/api/state/pref/ui_test").json()["value"] is None


@pytest.mark.skipif(not _es_up(), reason="needs Elasticsearch")
def test_triage_status_is_team_shared(client):
    # Shared kind → owner _team; round-trips independently of SSO identity.
    client.put("/api/state/triage_status/c-test", json="handled")
    items = client.get("/api/state/triage_status").json()["items"]
    assert any(it["key"] == "c-test" and it["value"] == "handled" for it in items)
    client.delete("/api/state/triage_status/c-test")
