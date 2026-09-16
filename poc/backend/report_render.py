"""Rendering helpers for the security operations report: ASCII sparkline and
per-period histogram bucket sizing. Pure functions, no I/O."""

from __future__ import annotations

from . import report_agg

_BLOCKS = "▁▂▃▄▅▆▇█"

_INTERVALS = {"daily": "1h", "weekly": "1d", "monthly": "1d"}


def bucket_interval(period: str) -> str:
    return _INTERVALS.get(period, "1d")


def sparkline(counts: list[int]) -> str:
    if not counts:
        return ""
    hi = max(counts)
    if hi <= 0:
        return _BLOCKS[0] * len(counts)
    out = []
    for c in counts:
        idx = int(round((c / hi) * (len(_BLOCKS) - 1)))
        out.append(_BLOCKS[max(0, min(idx, len(_BLOCKS) - 1))])
    return "".join(out)


def _kpi(label: str, value) -> str:
    return f"- **{label}**：{value}"


def _degraded_note(src: dict) -> list[str] | None:
    """Per-section marker for a source whose zeros are placeholders, not data.
    Returns None when the section's numbers are real."""
    reason = (src or {}).get("degraded")
    if not reason:
        return None
    return [f"> ⚠️ 本节数据获取失败，下方数字**不代表真实情况**：{reason}", ""]


def _section_exec(ctx: dict) -> list[str]:
    a = ctx["alerts"]
    an = ctx["analysis"]
    sev = {r["severity"]: r["count"] for r in a["severity"]}
    high = sev.get("critical", 0) + sev.get("high", 0)
    entities = len(a["top_entities"])
    return [
        "## 一、高管摘要", "",
        _kpi("告警总数", f"{a['total']:,}"),
        _kpi("严重 + 高危", f"{high:,}"),
        _kpi("受影响实体(Top)", entities),
        _kpi("本周期已分析/分诊", an["total"]),
        "",
    ]


def _section_alerts(ctx: dict) -> list[str]:
    a = ctx["alerts"]
    lines = ["## 二、告警态势", ""]
    note = _degraded_note(a)
    if note:
        return lines + note
    if a["total"] == 0:
        lines += ["_本周期无告警数据。_", ""]
        return lines
    spark = sparkline([b["count"] for b in a["timeline"]])
    lines += [
        _kpi("总量", f"{a['total']:,}"),
        _kpi("来源", f"poll {a['by_origin']['poll']:,} · webhook {a['by_origin']['webhook']:,}"),
        _kpi("时间序列", f"`{spark}`" if spark else "—"),
        "",
    ]
    return lines


def _bar(pct: float, width: int = 10) -> str:
    filled = int(round(pct / 100 * width))
    return "█" * filled + "·" * (width - filled)


def _section_severity(ctx: dict) -> list[str]:
    a = ctx["alerts"]
    lines = ["## 三、严重度分布", ""]
    note = _degraded_note(a)
    if note:
        return lines + note
    if a["total"] == 0:
        lines += ["_本周期无告警数据。_", ""]
        return lines
    lines += ["| 严重度 | 数量 | 占比 | |", "|---|---:|---:|---|"]
    for r in a["severity"]:
        lines.append(f"| {r['severity']} | {r['count']:,} | {r['pct']}% | `{_bar(r['pct'])}` |")
    lines.append("")
    return lines


def _section_rules(ctx: dict) -> list[str]:
    rules = ctx["alerts"]["top_rules"]
    lines = ["## 四、Top 检测规则", ""]
    note = _degraded_note(ctx["alerts"])
    if note:
        return lines + note
    if not rules:
        lines += ["_本周期无告警数据。_", ""]
        return lines
    lines += ["| 规则 | 告警数 | 主要严重度 |", "|---|---:|---|"]
    for r in rules:
        name = str(r["rule_name"]).replace("|", "\\|")
        lines.append(f"| {name} | {r['count']:,} | {r['severity'] or '—'} |")
    lines.append("")
    return lines


def _section_entities(ctx: dict) -> list[str]:
    ents = ctx["alerts"]["top_entities"]
    lines = ["## 五、Top 受影响实体", ""]
    note = _degraded_note(ctx["alerts"])
    if note:
        return lines + note
    if not ents:
        lines += ["_无受影响实体数据。_", ""]
        return lines
    lines += ["| 实体 | 类型 | 告警数 | 资产/业务名 | 关键度 |", "|---|---|---:|---|---|"]
    for e in ents:
        val = str(e["value"]).replace("|", "\\|")
        lines.append(
            f"| `{val}` | {e.get('field') or '—'} | {e['count']:,} | "
            f"{e.get('business_name') or '—'} | {e.get('criticality') or '—'} |")
    lines.append("")
    return lines


def _section_analysis(ctx: dict) -> list[str]:
    an = ctx["analysis"]
    lines = ["## 六、分析活动(闭环代理)", "",
             "> 以下为分析/分诊活动的**代理指标**,反映本周期处置投入,不代表真实处置闭环。", ""]
    note = _degraded_note(an)
    if note:
        return lines + note
    if an["total"] == 0:
        lines += ["_本周期无分析记录。_", ""]
        return lines
    lines += [
        _kpi("分析/分诊记录", f"{an['total']:,}(分诊 {an['by_kind']['triage']} · 调查 {an['by_kind']['investigation']})"),
        _kpi("高危已调查占比", f"{an['high_ratio'] * 100:.0f}%"),
        "",
    ]
    if an["top_topics"]:
        lines.append("**Top 调查主题**：")
        lines += [f"- {t}" for t in an["top_topics"]]
        lines.append("")
    return lines


def _section_baseline(ctx: dict) -> list[str]:
    b = ctx["baseline"]
    lines = ["## 七、基线合规", ""]
    note = _degraded_note(b)
    if note:
        return lines + note
    if b["run_at"] is None:
        lines += ["_暂无基线巡检数据。_", ""]
        return lines
    rate = "—" if b["pass_rate"] is None else f"{b['pass_rate']}%"
    lines += [
        _kpi("最近巡检", b["run_at"]),
        _kpi("达标率", rate),
        _kpi("判定分布", " / ".join(f"{k}:{v}" for k, v in b["by_verdict"].items()) or "—"),
        "",
    ]
    if b["top_fails"]:
        lines += ["**Top 不合规**：", "", "| 规则 | 主机 | 严重度 |", "|---|---|---|"]
        for f in b["top_fails"]:
            lines.append(f"| `{f.get('rule_id') or '—'}` | `{f.get('host') or '—'}` | {f.get('severity') or '—'} |")
        lines.append("")
    return lines


def _section_appendix(ctx: dict) -> list[str]:
    au = ctx["audit"]
    lines = ["## 附录 · AI 用量与系统健康", ""]
    note = _degraded_note(au)
    if note:
        return lines + note
    lines += [_kpi("AI 总调用", f"{au.get('total', 0):,}"),
              _kpi("成功率", f"{au.get('success_rate', 0.0) * 100:.1f}%"),
              ""]
    if au.get("by_action"):
        lines += ["| action | 次数 |", "|---|---:|"]
        for r in au["by_action"]:
            lines.append(f"| `{r['action']}` | {r['count']:,} |")
        lines.append("")
    return lines


def assemble_markdown(ctx: dict) -> str:
    md: list[str] = [
        f"# {ctx['label']}安全运营报告", "",
        f"- **生成时间**：{ctx['generated_at']}",
        f"- **周期**：{ctx['label']} ({ctx['start_at']} → {ctx['end_at']})",
        f"- **License**：`{ctx.get('license_status')}`",
        "",
    ]
    degraded = report_agg.collect_degraded(ctx)
    if degraded:
        # Up top, not buried: the exec summary right below is built from the same
        # placeholder zeros, and a reader who stops after 高管摘要 must still see it.
        md += ["> ⚠️ **本报告数据不完整。** 以下数据源获取失败，相关章节的数字为占位零值，"
               "不代表真实情况：", ""]
        md += [f">   - {report_agg.SOURCE_LABELS.get(d['source'], d['source'])}：{d['reason']}"
               for d in degraded]
        md += [""]
    md += _section_exec(ctx)
    md += _section_alerts(ctx)
    md += _section_severity(ctx)
    md += _section_rules(ctx)
    md += _section_entities(ctx)
    md += _section_analysis(ctx)
    md += _section_baseline(ctx)
    md += _section_appendix(ctx)
    md += ["---", "_由 RST Elastic AI Copilot 自动生成。请人工复核后再分发。_"]
    return "\n".join(md)
