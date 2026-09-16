import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import report_agg  # noqa: E402


class FakeAlertsES:
    """Returns a canned aggregation response shaped like ES."""
    def __init__(self, resp):
        self._resp = resp
        self.last_body = None

    async def search(self, index=None, body=None):
        self.last_body = body
        return type("R", (), {"body": self._resp})()


def _canned():
    return {
        "hits": {"total": {"value": 7}},
        "aggregations": {
            "timeline": {"buckets": [
                {"key_as_string": "2026-07-08T00:00:00Z", "doc_count": 3},
                {"key_as_string": "2026-07-08T01:00:00Z", "doc_count": 4},
            ]},
            "by_origin": {"buckets": [{"key": "poll", "doc_count": 5}, {"key": "webhook", "doc_count": 2}]},
            "by_severity": {"buckets": [
                {"key": "high", "doc_count": 4}, {"key": "low", "doc_count": 3}]},
            "top_rules": {"buckets": [
                {"key": "SSH 暴力破解", "doc_count": 4, "sev": {"buckets": [{"key": "high"}]}},
                {"key": "端口扫描", "doc_count": 3, "sev": {"buckets": [{"key": "low"}]}}]},
            "top_entities": {"buckets": [
                {"key": "10.0.0.5", "doc_count": 4, "fld": {"buckets": [{"key": "source.ip"}]}}]},
        },
    }


@pytest.mark.asyncio
async def test_alerts_aggregate_maps_all_dimensions():
    es = FakeAlertsES(_canned())
    out = await report_agg.alerts_aggregate(es, "2026-07-08T00:00:00Z", "2026-07-08T02:00:00Z", "1h")
    assert out["total"] == 7
    assert out["timeline"] == [
        {"ts": "2026-07-08T00:00:00Z", "count": 3},
        {"ts": "2026-07-08T01:00:00Z", "count": 4},
    ]
    assert out["by_origin"] == {"poll": 5, "webhook": 2}
    # severity is fixed 5-row order, missing filled with 0
    sev = {r["severity"]: r for r in out["severity"]}
    assert [r["severity"] for r in out["severity"]] == ["critical", "high", "medium", "low", "info"]
    assert sev["high"]["count"] == 4
    assert sev["critical"]["count"] == 0
    assert sev["high"]["pct"] == pytest.approx(57.1, abs=0.2)  # 4/7
    assert out["top_rules"][0] == {"rule_name": "SSH 暴力破解", "count": 4, "severity": "high"}
    assert out["top_entities"][0] == {"value": "10.0.0.5", "field": "source.ip", "count": 4}


@pytest.mark.asyncio
async def test_alerts_aggregate_degrades_on_error():
    class Boom:
        async def search(self, **kw):
            raise RuntimeError("index_not_found")
    out = await report_agg.alerts_aggregate(Boom(), "a", "b", "1h")
    assert out["total"] == 0
    assert out["timeline"] == []
    assert out["by_origin"] == {"poll": 0, "webhook": 0}
    assert len(out["severity"]) == 5
    assert all(r["count"] == 0 for r in out["severity"])
    assert out["top_rules"] == [] and out["top_entities"] == []


class HangingES:
    """Never returns — stands in for a dead cluster whose transport retries."""

    async def search(self, **kw):
        await asyncio.sleep(3600)


@pytest.mark.asyncio
async def test_alerts_aggregate_times_out_to_empty(monkeypatch):
    monkeypatch.setattr(report_agg, "ES_TIMEOUT_S", 0.05)
    started = time.monotonic()
    out = await report_agg.alerts_aggregate(HangingES(), "a", "b", "1h")
    assert time.monotonic() - started < 1.0  # bounded, not hung
    # Placeholder zeros, but FLAGGED — a report that prints "本周期无告警" because
    # ES timed out reads as a quiet night, which is the opposite of the truth.
    assert out["degraded"], "a timed-out source must not look like a quiet period"
    assert out == report_agg._empty_alerts(out["degraded"])


@pytest.mark.asyncio
async def test_analysis_activity_times_out_to_empty(monkeypatch):
    monkeypatch.setattr(report_agg, "ES_TIMEOUT_S", 0.05)
    out = await report_agg.analysis_activity(HangingES(), 0.0, 1.0)
    assert out["degraded"]
    assert out == report_agg._empty_analysis(out["degraded"])


@pytest.mark.asyncio
async def test_baseline_compliance_times_out_to_empty(monkeypatch):
    monkeypatch.setattr(report_agg, "ES_TIMEOUT_S", 0.05)

    async def hanging_latest_run():
        await asyncio.sleep(3600)

    async def unused_list_results(run_id=None):  # pragma: no cover
        raise AssertionError("should not be reached")

    out = await report_agg.baseline_compliance(hanging_latest_run, unused_list_results)
    assert out["degraded"]
    assert out == report_agg._empty_baseline(out["degraded"])


@pytest.mark.asyncio
async def test_enrich_entities_budget_is_shared_not_per_entity(monkeypatch):
    """A dead entity store must not cost ES_TIMEOUT_S per entity."""
    monkeypatch.setattr(report_agg, "ES_TIMEOUT_S", 0.1)
    ents = [{"value": f"h{i}", "field": "host.name", "count": 1} for i in range(10)]
    started = time.monotonic()
    out = await report_agg.enrich_entities(HangingES(), ents)
    assert time.monotonic() - started < 1.0  # one shared budget, not 10 × 0.1
    assert len(out) == 10
    assert all(r["business_name"] is None for r in out)
