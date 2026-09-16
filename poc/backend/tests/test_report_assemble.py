import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import report_render as rr  # noqa: E402
from backend.report_agg import _empty_alerts, _empty_analysis, _empty_baseline  # noqa: E402


def _audit_stub():
    return {"total": 0, "success": 0, "fail": 0, "success_rate": 0.0,
            "by_action": [], "top_indexes": [], "top_users": []}


def _full_ctx():
    return {
        "label": "过去 24 小时", "generated_at": "t", "start_at": "s", "end_at": "e",
        "license_status": "active",
        "alerts": {
            "total": 7,
            "timeline": [{"ts": "2026-07-08T00:00:00Z", "count": 3},
                         {"ts": "2026-07-08T01:00:00Z", "count": 4}],
            "by_origin": {"poll": 5, "webhook": 2},
            "severity": [{"severity": "critical", "count": 0, "pct": 0.0},
                         {"severity": "high", "count": 4, "pct": 57.1},
                         {"severity": "medium", "count": 0, "pct": 0.0},
                         {"severity": "low", "count": 3, "pct": 42.9},
                         {"severity": "info", "count": 0, "pct": 0.0}],
            "top_rules": [{"rule_name": "SSH 暴力破解", "count": 4, "severity": "high"}],
            "top_entities": [{"value": "WIN-DB01", "field": "host.name", "count": 4,
                              "business_name": "核心数据库", "criticality": "high", "owner": "dba"}],
        },
        "analysis": {"total": 5, "by_kind": {"triage": 3, "investigation": 2},
                     "high_ratio": 0.6, "top_topics": ["SSH 暴力破解"]},
        "baseline": {"run_at": "2026-07-08T00:00:00Z", "pass_rate": 80.0,
                     "by_verdict": {"pass": 8, "fail": 2},
                     "top_fails": [{"rule_id": "b", "host": "h2", "severity": "critical"}]},
        "audit": _audit_stub(),
    }


def test_assemble_has_all_section_titles():
    md = rr.assemble_markdown(_full_ctx())
    for title in ["## 一、高管摘要", "## 二、告警态势", "## 三、严重度分布",
                  "## 四、Top 检测规则", "## 五、Top 受影响实体",
                  "## 六、分析活动(闭环代理)", "## 七、基线合规",
                  "## 附录 · AI 用量与系统健康"]:
        assert title in md


def test_assemble_renders_data_points():
    md = rr.assemble_markdown(_full_ctx())
    assert "SSH 暴力破解" in md
    assert "核心数据库" in md           # enriched asset name
    assert "80.0" in md                  # baseline pass rate
    # sparkline present (some block char from the timeline)
    assert any(ch in md for ch in "▁▂▃▄▅▆▇█")


def test_assemble_section_six_is_proxy_not_real_closure():
    md = rr.assemble_markdown(_full_ctx())
    assert "代理" in md                  # section 6 disclaimer
    assert "闭环率" not in md            # must NOT claim a real closure rate


def test_assemble_empty_sources_show_placeholders():
    ctx = {"label": "过去 24 小时", "generated_at": "t", "start_at": "s", "end_at": "e",
           "license_status": "unknown",
           "alerts": _empty_alerts(), "analysis": _empty_analysis(),
           "baseline": _empty_baseline(), "audit": _audit_stub()}
    md = rr.assemble_markdown(ctx)
    assert "_本周期无告警数据。_" in md
    assert "_本周期无分析记录。_" in md
    assert "_暂无基线巡检数据。_" in md
    # still contains every section title (report never collapses)
    assert "## 二、告警态势" in md and "## 七、基线合规" in md
    assert "数据不完整" not in md, "genuine zeros must not be flagged as degraded"


def test_a_failed_source_is_never_rendered_as_a_quiet_period():
    """The whole point: ES timed out, so alerts is zeros. Printing
    "_本周期无告警数据。_" tells the operator the night was quiet when in fact
    nothing was read. Both the header and the section must say so."""
    ctx = {"label": "过去 24 小时", "generated_at": "t", "start_at": "s", "end_at": "e",
           "license_status": "active",
           "alerts": _empty_alerts("TimeoutError"), "analysis": _empty_analysis(),
           "baseline": _empty_baseline(), "audit": _audit_stub()}
    md = rr.assemble_markdown(ctx)

    assert "本报告数据不完整" in md, "the header must warn before the exec summary"
    assert "TimeoutError" in md, "the reason must be visible, not only in the log"
    assert "_本周期无告警数据。_" not in md, "the false 'quiet period' claim must be gone"
    # sections fed by the failed source all carry the marker, not zero tables
    assert md.count("本节数据获取失败") == 4  # 二 / 三 / 四 / 五
    # unaffected sections keep their normal placeholders
    assert "_本周期无分析记录。_" in md
