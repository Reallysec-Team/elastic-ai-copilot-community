import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import reports  # noqa: E402


@pytest.mark.asyncio
async def test_generate_orchestrates_all_sections(monkeypatch):
    async def fake_alerts_aggregate(es, s, e, interval):
        return {"total": 7, "timeline": [{"ts": "x", "count": 7}],
                "by_origin": {"poll": 7, "webhook": 0},
                "severity": [{"severity": sv, "count": (7 if sv == "high" else 0),
                              "pct": (100.0 if sv == "high" else 0.0)}
                             for sv in ["critical", "high", "medium", "low", "info"]],
                "top_rules": [{"rule_name": "R", "count": 7, "severity": "high"}],
                "top_entities": [{"value": "H", "field": "host.name", "count": 7}]}

    async def fake_enrich(es, ents):
        return [{**e, "business_name": "BN", "criticality": "high", "owner": "o"} for e in ents]

    async def fake_analysis(es, s, e):
        return {"total": 3, "by_kind": {"triage": 2, "investigation": 1},
                "high_ratio": 0.33, "top_topics": ["T"]}

    async def fake_baseline(lr, lres):
        return {"run_at": "r", "pass_rate": 90.0, "by_verdict": {"pass": 9, "fail": 1}, "top_fails": []}

    async def fake_audit(s, e):
        return reports._empty_summary()

    monkeypatch.setattr(reports.report_agg, "alerts_aggregate", fake_alerts_aggregate)
    monkeypatch.setattr(reports.report_agg, "enrich_entities", fake_enrich)
    monkeypatch.setattr(reports.report_agg, "analysis_activity", fake_analysis)
    monkeypatch.setattr(reports.report_agg, "baseline_compliance", fake_baseline)
    monkeypatch.setattr(reports, "_summarize_audit", fake_audit)
    monkeypatch.setattr(reports, "get_es", lambda: object())

    out = await reports.generate("daily")

    # envelope keys preserved
    for k in ["period", "label", "generated_at", "start_at", "end_at", "markdown", "summary", "license_status"]:
        assert k in out
    assert out["period"] == "daily"
    # new summary shape
    assert set(out["summary"].keys()) >= {"exec", "alerts", "analysis", "baseline", "audit"}
    assert out["summary"]["alerts"]["total"] == 7
    # enrichment applied to entities
    assert out["summary"]["alerts"]["top_entities"][0]["business_name"] == "BN"
    # markdown assembled with new titles + enriched data
    assert "## 二、告警态势" in out["markdown"]
    assert "BN" in out["markdown"]
    assert "## 附录 · AI 用量与系统健康" in out["markdown"]


@pytest.mark.asyncio
async def test_generate_rejects_unknown_period():
    with pytest.raises(ValueError):
        await reports.generate("yearly")
