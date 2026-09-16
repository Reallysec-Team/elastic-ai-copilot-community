"""The /api/platform/checkup route: license gate, audit trail, error shape.

The checks themselves are covered by test_platform_ops.py — here we only care
that the endpoint is gated like every other paid surface (the audit found
baseline_router mounted with no gate at all, which is the mistake this avoids)
and that it records an audit event, since these calls reach past every
guardrail the search path has.
"""
import os
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent  # .../poc
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

os.environ.pop("RST_GATEWAY_SHARED_SECRET", None)
os.environ.pop("RST_ADMIN_TOKEN", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import audit, license_state, main, platform_ops_routes  # noqa: E402
from backend.platform_ops import checks, interpret as interpret_mod  # noqa: E402

_REPORT = {
    "generated_at": "2026-09-03T00:00:00+00:00",
    "verdict": "warn",
    "counts": {"ok": 4, "warn": 1, "fail": 0, "unknown": 1},
    "checks": [
        {"id": "cluster_health", "title": "集群健康", "verdict": "warn",
         "summary": "单节点集群", "detail": {}, "advice": ""},
    ],
}


@pytest.fixture(autouse=True)
def _licensed(monkeypatch):
    """See test_solutions_wiring — the license gate 403s everything once an
    earlier test in the session has left the state at heartbeat_lost."""
    monkeypatch.setattr(
        license_state, "get_state",
        lambda: {"status": license_state.STATUS_VALID, "features": ["*"]},
    )


@pytest.fixture
def _no_audit(monkeypatch):
    events: list = []

    async def fake_write(action, **kw):
        events.append((action, kw))

    monkeypatch.setattr(audit, "write_event", fake_write)
    return events


def _ok_checks(monkeypatch):
    async def fake_run_all():
        return _REPORT

    monkeypatch.setattr(checks, "run_all", fake_run_all)


def test_checkup_returns_the_report(monkeypatch, _no_audit):
    _ok_checks(monkeypatch)
    monkeypatch.setattr(license_state, "feature_allowed", lambda _f: True)
    r = TestClient(main.app).get("/api/platform/checkup")
    assert r.status_code == 200
    assert r.json()["verdict"] == "warn"
    assert r.json()["counts"]["ok"] == 4


def test_checkup_is_license_gated(monkeypatch, _no_audit):
    """Not repeating baseline_router's mistake of mounting a paid surface with
    no feature check at all."""
    _ok_checks(monkeypatch)
    monkeypatch.setattr(license_state, "feature_allowed", lambda _f: False)
    r = TestClient(main.app).get("/api/platform/checkup")
    assert r.status_code == 403


def test_the_gate_asks_for_the_right_feature(monkeypatch, _no_audit):
    asked: list = []
    _ok_checks(monkeypatch)
    monkeypatch.setattr(license_state, "feature_allowed",
                        lambda f: asked.append(f) or True)
    TestClient(main.app).get("/api/platform/checkup")
    assert asked == ["platform_ops_copilot"]


def test_checkup_is_audited(monkeypatch, _no_audit):
    """These calls bypass validate_dsl / the index whitelist / masking, so the
    audit log is the only record that the gateway read the cluster at all."""
    _ok_checks(monkeypatch)
    monkeypatch.setattr(license_state, "feature_allowed", lambda _f: True)
    TestClient(main.app).get("/api/platform/checkup")
    actions = [a for a, _ in _no_audit]
    assert "platform_checkup" in actions
    kw = next(kw for a, kw in _no_audit if a == "platform_checkup")
    assert kw["extra"]["verdict"] == "warn"
    assert kw["extra"]["checks"] == ["cluster_health"]


def test_a_blown_up_checkup_is_a_500_not_a_crash(monkeypatch, _no_audit):
    async def boom():
        raise RuntimeError("es unreachable")

    monkeypatch.setattr(checks, "run_all", boom)
    monkeypatch.setattr(license_state, "feature_allowed", lambda _f: True)
    r = TestClient(main.app).get("/api/platform/checkup")
    assert r.status_code == 500
    assert "平台体检失败" in r.json()["detail"]


# ── /api/platform/interpret ─────────────────────────────────────────────────

_READING = {"conclusion": "接入已中断", "actions": [], "degraded": False, "rag_chunks_used": 2}


def _stub_interpret(monkeypatch, report=None, reading=None):
    async def fake_run_all():
        return report if report is not None else _REPORT

    async def fake_interpret(_report):
        return reading if reading is not None else _READING

    monkeypatch.setattr(checks, "run_all", fake_run_all)
    monkeypatch.setattr(interpret_mod, "interpret", fake_interpret)
    monkeypatch.setattr(license_state, "feature_allowed", lambda _f: True)


def test_interpret_returns_both_report_and_reading(monkeypatch, _no_audit):
    """The caller gets the findings the reading was made from, so the two on
    screen can never disagree."""
    _stub_interpret(monkeypatch)
    r = TestClient(main.app).post("/api/platform/interpret")
    assert r.status_code == 200
    body = r.json()
    assert body["report"]["verdict"] == "warn"
    assert body["interpretation"]["conclusion"] == "接入已中断"


def test_interpret_is_license_gated(monkeypatch, _no_audit):
    _stub_interpret(monkeypatch)
    monkeypatch.setattr(license_state, "feature_allowed", lambda _f: False)
    assert TestClient(main.app).post("/api/platform/interpret").status_code == 403


def test_a_healthy_cluster_refunds_the_trial_unit(monkeypatch, _no_audit):
    """The gate charges before the handler runs, but an all-ok report never
    reaches the LLM — don't bill a demo user for a call we didn't make."""
    refunds: list = []

    async def fake_refund():
        refunds.append(1)

    _stub_interpret(monkeypatch, report={**_REPORT, "verdict": "ok"})
    monkeypatch.setattr(license_state, "get_state",
                        lambda: {"status": license_state.STATUS_UNACTIVATED, "features": ["*"]})
    monkeypatch.setattr(license_state, "refund_unactivated_quota", fake_refund)
    TestClient(main.app).post("/api/platform/interpret")
    assert len(refunds) == 1


def test_a_problem_report_is_billed(monkeypatch, _no_audit):
    refunds: list = []

    async def fake_refund():
        refunds.append(1)

    _stub_interpret(monkeypatch)  # verdict == "warn"
    monkeypatch.setattr(license_state, "get_state",
                        lambda: {"status": license_state.STATUS_UNACTIVATED, "features": ["*"]})
    monkeypatch.setattr(license_state, "refund_unactivated_quota", fake_refund)
    TestClient(main.app).post("/api/platform/interpret")
    assert refunds == []


def test_interpret_is_audited(monkeypatch, _no_audit):
    _stub_interpret(monkeypatch)
    TestClient(main.app).post("/api/platform/interpret")
    kw = next(kw for a, kw in _no_audit if a == "platform_interpret")
    assert kw["extra"]["degraded"] is False
    assert kw["extra"]["rag_chunks_used"] == 2
