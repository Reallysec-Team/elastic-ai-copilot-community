import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import report_agg  # noqa: E402


@pytest.mark.asyncio
async def test_baseline_compliance_computes_pass_rate_and_top_fails():
    async def latest_run():
        return {"run_id": "r1", "finished_at": "2026-07-08T00:00:00Z"}

    async def list_results(run_id=None):
        assert run_id == "r1"
        return [
            {"verdict": "pass", "rule_id": "a", "host": "h1", "severity": "low"},
            {"verdict": "fail", "rule_id": "b", "host": "h2", "severity": "critical"},
            {"verdict": "fail", "rule_id": "c", "host": "h3", "severity": "medium"},
            {"verdict": "pass", "rule_id": "d", "host": "h4", "severity": "info"},
        ]

    out = await report_agg.baseline_compliance(latest_run, list_results)
    assert out["run_at"] == "2026-07-08T00:00:00Z"
    assert out["pass_rate"] == 50.0  # 2/4
    assert out["by_verdict"] == {"pass": 2, "fail": 2}
    # critical fail sorts before medium fail
    assert out["top_fails"][0] == {"rule_id": "b", "host": "h2", "severity": "critical"}
    assert out["top_fails"][1]["severity"] == "medium"


@pytest.mark.asyncio
async def test_baseline_compliance_no_run_returns_empty():
    async def latest_run():
        return None

    async def list_results(run_id=None):  # pragma: no cover — must not be called
        raise AssertionError("should not query results without a run")

    out = await report_agg.baseline_compliance(latest_run, list_results)
    assert out == {"run_at": None, "pass_rate": None, "by_verdict": {}, "top_fails": [],
                   # "never run" is a real answer, not a failed fetch
                   "degraded": None}


@pytest.mark.asyncio
async def test_baseline_compliance_degrades_on_error():
    async def latest_run():
        raise RuntimeError("baseline-runs missing")

    async def list_results(run_id=None):
        return []

    out = await report_agg.baseline_compliance(latest_run, list_results)
    assert out["pass_rate"] is None and out["top_fails"] == []
