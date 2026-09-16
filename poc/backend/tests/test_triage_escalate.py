"""POST /api/triage/escalate — turns the 升级 disposition into an on-call push.

Verifies the endpoint builds the alert shape dispatch_alert expects (升级-prefixed
rule_name, subject fields carried through) and reports the dispatched count, plus
the empty-cluster guard.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import main  # noqa: E402
from backend.notify import outbox  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "_feature_allowed", lambda feature: True)
    return TestClient(main.app)


def test_escalate_builds_alert_and_reports_count(client, monkeypatch):
    seen = {}

    async def fake_dispatch(alert, ref):
        seen["alert"] = alert
        seen["ref"] = ref
        return 2

    monkeypatch.setattr(outbox, "dispatch_alert", fake_dispatch)

    cluster = {
        "cluster_id": "c1",
        "priority_rank": 3,
        "severity": "high",
        "attack_intent": "暴力破解",
        "subject_field": "source.ip",
        "subject_value": "10.0.0.5",
        "recommendation": "封禁该 IP",
        "count": 42,
    }
    r = client.post("/api/triage/escalate", json={"cluster": cluster})
    assert r.status_code == 200
    assert r.json()["dispatched"] == 2

    a = seen["alert"]
    assert a["severity"] == "high"
    assert a["rule_name"] == "[升级 #3] 暴力破解"
    assert a["subject_field"] == "source.ip" and a["subject_value"] == "10.0.0.5"
    assert a["recommendation"] == "封禁该 IP"
    assert seen["ref"].startswith("escalate:c1:")


def test_escalate_synthesizes_recommendation_when_missing(client, monkeypatch):
    seen = {}

    async def fake_dispatch(alert, ref):
        seen["alert"] = alert
        return 0

    monkeypatch.setattr(outbox, "dispatch_alert", fake_dispatch)
    r = client.post("/api/triage/escalate", json={"cluster": {"count": 7, "severity": "medium"}})
    assert r.status_code == 200
    assert r.json()["dispatched"] == 0  # no targets → graceful
    assert "7 条告警" in seen["alert"]["recommendation"]


def test_escalate_rejects_empty_cluster(client):
    assert client.post("/api/triage/escalate", json={}).status_code == 400
    assert client.post("/api/triage/escalate", json={"cluster": {}}).status_code == 400
