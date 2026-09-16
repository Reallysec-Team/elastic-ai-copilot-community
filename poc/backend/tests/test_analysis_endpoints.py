"""Read endpoints — owner-scoped list + detail, 404 on miss/foreign."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import analysis_store, main  # noqa: E402


@pytest.fixture
def client():
    return TestClient(main.app)


def test_list_passes_params_to_store(client, monkeypatch):
    seen = {}

    async def fake_list(kind, limit, before, owner, es=None, q=None, since=None):
        seen.update(kind=kind, limit=limit, before=before, owner=owner, q=q, since=since)
        return {"total": 1, "records": [{"id": "a", "kind": "triage"}]}

    monkeypatch.setattr(analysis_store, "list_records", fake_list)
    r = client.get("/api/analysis?kind=triage&limit=5&before=123.0&q=暴力破解&since=100.0")
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert seen["kind"] == "triage" and seen["limit"] == 5 and seen["before"] == 123.0
    assert seen["q"] == "暴力破解" and seen["since"] == 100.0


def test_detail_404_when_missing(client, monkeypatch):
    async def none(*a, **k):
        return None

    monkeypatch.setattr(analysis_store, "get_record", none)
    assert client.get("/api/analysis/nope").status_code == 404


def test_detail_returns_record(client, monkeypatch):
    async def one(rec_id, owner=None, es=None):
        return {"id": rec_id, "kind": "investigation", "payload": {"summary": "x"}}

    monkeypatch.setattr(analysis_store, "get_record", one)
    r = client.get("/api/analysis/abc")
    assert r.status_code == 200 and r.json()["payload"] == {"summary": "x"}
