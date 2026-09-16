"""中立投递事件 —— 生产者产它，渠道渲染它。

原来报告调度器和告警摄取直接产飞书卡片。接第二个平台时第一个炸的就是这里：钉钉
的 markdown、企业微信的 markdown、邮件的 HTML 谁也不认飞书的 card schema，而卡片
是在生产者那儿拼好的，等于每加一个渠道就要回去改一次生产者。

现在生产者只回答「发生了什么」：标题、严重度、若干条 (标签, 值)、正文、链接。
「长什么样」归渠道。

值一律是**已经格式化好的字符串**（`1,234`、`97%`），不是原始数字 —— 千分位和百分号
是内容的一部分，不该让四个渠道各写一遍。转义则相反，归渠道：飞书要转 lark_md 的
元字符，邮件要转 HTML 实体，规则不一样。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]


@dataclass(frozen=True)
class Payload:
    #: 'report' | 'alert' —— 生产者，不是渠道
    kind: str
    #: 事件主体（"过去 24 小时" / 规则名），渠道拿它拼自己的标题
    subject: str
    #: 完整标题（"安全巡检报告 · 过去 24 小时"）
    heading: str
    severity: str
    #: (标签, 值)，顺序即展示顺序
    fields: tuple[tuple[str, str], ...] = ()
    #: 正文全文。只有邮件用得上 —— IM 卡片有 ~30KB 上限，塞不进去。
    body_md: str = ""
    #: 产品内的完整链接，空表示不给按钮
    link: str = ""
    #: 值里含攻击者可控内容（规则名、主体值、建议）。渠道据此决定转义力度；
    #: 目前四个渠道都是无条件转义，留着是为了让这件事在数据里是显式的。
    untrusted: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def worst_severity(counts: dict[str, int] | None) -> str:
    """一份 {severity: n} 里最狠的那档。空 → info。"""
    if not counts:
        return "info"
    present = [s for s in SEVERITY_ORDER if counts.get(s)]
    return present[-1] if present else "info"


def _link(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}" if base_url else ""


def from_report(report: dict[str, Any], *, base_url: str = "") -> Payload:
    label = report.get("label") or report.get("period") or "巡检报告"
    summary = report.get("summary") or {}
    sec = report.get("security_triage") or {}
    rate = summary.get("success_rate")

    fields: list[tuple[str, str]] = [
        ("周期", str(label)),
        ("区间", f"{report.get('start_at', '?')} → {report.get('end_at', '?')}"),
        ("调用总数", f"{summary.get('total', 0):,}"),
        ("成功率", f"{rate:.0%}" if isinstance(rate, (int, float)) else "—"),
        ("唯一用户", str(summary.get("unique_users", 0))),
        ("唯一索引", str(summary.get("unique_indexes", 0))),
    ]
    if sec:
        fields.append((
            "告警分诊",
            f"告警 {sec.get('total_alerts', 0):,} · 聚类 {sec.get('total_clusters', 0)}"
            f" · 疑似误报 {sec.get('likely_fp', 0)}",
        ))
    if report.get("license_status"):
        fields.append(("License", str(report["license_status"])))

    return Payload(
        kind="report",
        subject=str(label),
        heading=f"安全巡检报告 · {label}",
        severity=worst_severity(sec.get("severity_counts")),
        fields=tuple(fields),
        body_md=str(report.get("markdown") or ""),
        link=_link(base_url, "/v2/reports"),
        extra={"end_at": report.get("end_at", "")},
    )


def from_alert(alert: dict[str, Any], *, base_url: str = "") -> Payload:
    severity = (alert.get("severity") or "info").lower()
    subject = (
        alert.get("rule_name") or alert.get("rule_id")
        or alert.get("attack_intent") or alert.get("title") or "安全告警"
    )

    fields: list[tuple[str, str]] = [("严重度", severity.upper())]
    if alert.get("attack_intent"):
        fields.append(("攻击意图", str(alert["attack_intent"])))
    subj_field, subj_value = alert.get("subject_field"), alert.get("subject_value")
    if subj_field or subj_value:
        fields.append(("主体", f"{subj_field or '?'} = {subj_value or '?'}"))
    if alert.get("count"):
        c = alert["count"]
        fields.append(("命中数", f"{int(c):,}" if str(c).isdigit() else str(c)))
    when = alert.get("last_seen") or alert.get("occurred_at") or alert.get("@timestamp")
    if when:
        fields.append(("时间", str(when)))
    if alert.get("summary"):
        fields.append(("摘要", str(alert["summary"])))
    if alert.get("recommendation"):
        fields.append(("建议", str(alert["recommendation"])))

    return Payload(
        kind="alert",
        subject=str(subject),
        heading=f"实时告警 · {subject}",
        severity=severity,
        fields=tuple(fields),
        # 告警去向是外部服务，规则名和主体值都可能是攻击者写进日志的东西。
        untrusted=True,
        link=_link(base_url, "/v2/triage"),
    )
