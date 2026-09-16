"""Route writes are best-effort: a record() failure must not break the endpoint."""
import os
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent  # .../poc
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

# Demo mode (open) + no license BEFORE importing the app (mirrors test_api_state.py).
os.environ.pop("RST_GATEWAY_SHARED_SECRET", None)
os.environ.pop("RST_ADMIN_TOKEN", None)

from backend import agentic_investigate, analysis_store, main  # noqa: E402


def test_record_failure_does_not_break_investigate(monkeypatch):
    from fastapi.testclient import TestClient

    canned_result = {"alert_type": "T", "severity": "low", "summary": "s"}

    async def fake_investigate_alert(*a, **k):
        return canned_result

    async def boom(*a, **k):
        raise RuntimeError("record down")

    monkeypatch.setattr(main, "_feature_allowed", lambda *a, **k: True)
    monkeypatch.setattr(main, "_check_index", lambda *a, **k: None)
    monkeypatch.setattr(agentic_investigate, "agentic_enabled", lambda: False)
    monkeypatch.setattr(main, "investigate_alert", fake_investigate_alert)
    monkeypatch.setattr(analysis_store, "record", boom)

    with TestClient(main.app) as client:
        r = client.post(
            "/api/investigate-alert",
            json={"alert": {"foo": "bar"}, "index": "logs-*"},
        )

    # A record() failure must not break or alter the endpoint response.
    assert r.status_code == 200
    assert r.json() == canned_result


def test_endpoints_reference_analysis_store():
    # Guard: both endpoints wire the archive write.
    src = Path(main.__file__).read_text(encoding="utf-8")
    assert src.count("analysis_store.record(") >= 2
    assert 'analysis_store.record("investigation"' in src
    assert 'analysis_store.record("triage"' in src
