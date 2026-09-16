"""Incident report generation: render a SOC-shippable Markdown report from an
alert + its investigation result.

NOT `reports.py` — that one is the periodic operational report (daily / weekly /
monthly), together with its `report_agg` / `report_render` / `report_scheduler`
helpers. This module used to be called `report.py`, one letter from it, for two
unrelated things; the route paths carry the same trap (`/api/report/incident`
here, `/api/reports/*` there).

Pipeline:
  1. resolve the alert (passed in directly or fetched by id)
  2. run investigate_alert if the caller didn't already supply one
  3. gather a small evidence appendix (raw nearby logs)
  4. one short LLM call for an executive-summary paragraph
  5. render Markdown deterministically from the structured pieces

The investigation step is the heavy LLM call; the executive summary is a tiny
follow-up. Markdown rendering itself uses no LLM — predictable layout and zero
extra cost when the caller passes in a cached `investigation`.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from .es_client import get_es
from .field_masking import mask_doc
from .investigate import investigate_alert, _SUBJECT_FIELDS, _get_nested
from .llm_router import get_router
from .rag import augment_prompt_meta

logger = logging.getLogger("rst.report")


_EXEC_SUMMARY_SYSTEM_PROMPT = """你是 SOC 高级分析师。基于已有的事件调查结论，写一段 80-150 字的中文执行摘要，给安全运营管理层看。要点：
- 一句话说清这次事件是什么、谁是受影响的主体（IP / 用户 / 主机）
- 严重程度、是否疑似误报（False Positive）
- 一句话推荐管理层是否需要介入

只输出纯文本一段话，不要 Markdown 标题、不要列表、不要代码块、不要 JSON。
如用户消息以 "Reference materials:" 段开头，那是来自客户知识库的检索结果，可参考其中的业务背景；若与告警事实冲突，以告警事实为准。
"""


async def generate_incident_report(
    *,
    index: str,
    alert: dict[str, Any] | None = None,
    alert_id: str | None = None,
    investigation: dict[str, Any] | None = None,
    window_minutes: int = 30,
    include_evidence: bool = True,
    evidence_limit: int = 10,
) -> dict[str, Any]:
    if alert is None and alert_id is None and investigation is None:
        raise ValueError("at least one of alert, alert_id, or investigation must be provided")

    alert_src = await _resolve_alert(index, alert, alert_id)

    if investigation is None:
        investigation = await investigate_alert(alert_src, index, window_minutes=window_minutes)

    evidence: list[dict[str, Any]] = []
    if include_evidence:
        evidence = await _gather_evidence(alert_src, index, window_minutes, evidence_limit)

    exec_summary, rag_used = await _exec_summary(alert_src, investigation)

    markdown = _render_markdown(
        alert_src=alert_src,
        investigation=investigation,
        evidence=evidence,
        exec_summary=exec_summary,
        index=index,
        alert_id=alert_id,
        window_minutes=window_minutes,
    )

    title = f"安全事件报告：{investigation.get('alert_type') or 'Unknown'}"

    return {
        "title": title,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "markdown": markdown,
        "exec_summary": exec_summary,
        "investigation": investigation,
        "evidence_count": len(evidence),
        "rag_chunks_used": rag_used,
        "metadata": {
            "index": index,
            "alert_id": alert_id,
            "window_minutes": window_minutes,
            "include_evidence": include_evidence,
        },
    }


async def _resolve_alert(
    index: str, alert: dict[str, Any] | None, alert_id: str | None
) -> dict[str, Any]:
    if alert is not None:
        src = alert.get("_source") if "_source" in alert else alert
        return src if isinstance(src, dict) else {}
    if alert_id:
        try:
            es = get_es()
            resp = await es.get(index=index, id=alert_id)
            src = (resp.body or {}).get("_source") or {}
            return src if isinstance(src, dict) else {}
        except Exception as e:
            raise ValueError(f"failed to fetch alert_id={alert_id} from index={index}: {e}")
    return {}


async def _gather_evidence(
    alert_src: dict[str, Any], index: str, window_minutes: int, limit: int
) -> list[dict[str, Any]]:
    subject_field, subject_value = None, None
    for field in _SUBJECT_FIELDS:
        v = _get_nested(alert_src, field)
        if v is not None and str(v).strip():
            subject_field = field
            subject_value = str(v)
            break
    if not subject_field:
        return []

    es = get_es()
    time_filter = {"range": {"@timestamp": {"gte": f"now-{window_minutes}m"}}}
    for fld_variant in (f"{subject_field}.keyword", subject_field):
        try:
            resp = await es.search(
                index=index,
                body={
                    "query": {
                        "bool": {
                            "filter": [
                                time_filter,
                                {"term": {fld_variant: subject_value}},
                            ]
                        }
                    },
                    "size": limit,
                    "sort": [{"@timestamp": "desc"}],
                },
            )
            hits = (resp.body.get("hits") or {}).get("hits") or []
            return [
                {
                    "_id": h.get("_id"),
                    "_index": h.get("_index"),
                    "@timestamp": (h.get("_source") or {}).get("@timestamp"),
                    "_source": mask_doc(h.get("_source", {})),
                }
                for h in hits
            ]
        except Exception as e:
            logger.debug(f"evidence query failed for {fld_variant}: {e}")
            continue
    return []


async def _exec_summary(alert_src: dict[str, Any], investigation: dict[str, Any]) -> tuple[str, int]:
    masked_alert = mask_doc(alert_src)
    user_prompt = (
        f"告警摘要(已脱敏)：\n"
        f"  类型：{investigation.get('alert_type', 'unknown')}\n"
        f"  严重程度：{investigation.get('severity', 'info')}\n"
        f"  疑似误报：{investigation.get('is_likely_false_positive', False)}\n"
        f"  调查结论：{investigation.get('summary', '')}\n"
        f"\n"
        f"受影响资产：{investigation.get('affected_assets', [])}\n"
        f"建议处置：{investigation.get('recommended_actions', [])}\n"
        f"\n"
        f"原始告警字段（截断）：{str(masked_alert)[:1200]}\n"
        f"\n按系统提示生成 80-150 字的中文执行摘要，单段纯文本。"
    )
    user_prompt, rag_used = await augment_prompt_meta(user_prompt, top_k=2)
    try:
        resp, _provider = await get_router().chat_completion(
            messages=[
                {"role": "system", "content": _EXEC_SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            reasoning="low",  # 报表叙述：按模板写
        )
        text = (resp.choices[0].message.content or "").strip()
        if len(text) > 600:
            text = text[:599] + "…"
        return text, rag_used
    except Exception as e:
        logger.warning("exec_summary_failed", extra={"error": str(e)[:300]})
        return investigation.get("summary", "") or "", rag_used


def _render_markdown(
    *,
    alert_src: dict[str, Any],
    investigation: dict[str, Any],
    evidence: list[dict[str, Any]],
    exec_summary: str,
    index: str,
    alert_id: str | None,
    window_minutes: int,
) -> str:
    # A caller-supplied `investigation` (report.py:54 path) is NOT run through
    # investigate._normalize, so any field may be None or the wrong type. Render
    # defensively — a report must never 500 on malformed investigation input.
    sev = investigation.get("severity") or "info"
    alert_type = investigation.get("alert_type") or "Unknown"
    is_fp = bool(investigation.get("is_likely_false_positive"))
    fp_reason = investigation.get("false_positive_reason") or ""

    lines: list[str] = []
    lines.append(f"# 安全事件报告 — {alert_type}")
    lines.append("")
    lines.append(f"- **生成时间**：{datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- **索引**：`{index}`")
    if alert_id:
        lines.append(f"- **告警 ID**：`{alert_id}`")
    lines.append(f"- **上下文窗口**：最近 {window_minutes} 分钟")
    lines.append(f"- **严重程度**：**{str(sev).upper()}**")
    lines.append(f"- **置信度**：{investigation.get('confidence', 'medium')}")
    lines.append(f"- **疑似误报**：{'是' if is_fp else '否'}{('（' + fp_reason + '）') if (is_fp and fp_reason) else ''}")
    lines.append("")

    lines.append("## 执行摘要")
    lines.append("")
    lines.append(exec_summary or investigation.get("summary", "") or "_(未生成)_")
    lines.append("")

    lines.append("## 调查结论")
    lines.append("")
    lines.append(investigation.get("summary", "") or "_(未提供)_")
    lines.append("")

    timeline = investigation.get("timeline") or []
    if timeline:
        lines.append("## 时间线")
        lines.append("")
        for item in timeline:
            if not isinstance(item, dict):
                lines.append(f"- {item}")
                continue
            t = item.get("time", "?")
            ev = item.get("event", "")
            lines.append(f"- **{t}** — {ev}")
        lines.append("")

    chain = investigation.get("attack_chain") or []
    if chain:
        lines.append("## 攻击链（MITRE 战术阶段）")
        lines.append("")
        for item in chain:
            if not isinstance(item, dict):
                lines.append(f"- {item}")
                continue
            phase = item.get("phase", "?")
            evid = item.get("evidence", "")
            lines.append(f"- **{phase}** — {evid}")
        lines.append("")

    techniques = investigation.get("mitre_techniques") or []
    if techniques:
        lines.append("## MITRE ATT&CK 技术")
        lines.append("")
        lines.append("| ID | 技术名 | 证据 |")
        lines.append("|---|---|---|")
        for tech in techniques:
            if not isinstance(tech, dict):
                tech = {"name": tech}
            tid = _md_cell(tech.get("id", ""))
            tname = _md_cell(tech.get("name", ""))
            tevid = _md_cell(tech.get("evidence", ""))
            lines.append(f"| {tid} | {tname} | {tevid} |")
        lines.append("")

    assets = investigation.get("affected_assets") or []
    if assets:
        lines.append("## 受影响资产")
        lines.append("")
        for a in assets:
            if not isinstance(a, dict):
                lines.append(f"- `{a}`")
                continue
            lines.append(f"- `{a.get('type', '?')}` : `{a.get('id', '')}`")
        lines.append("")

    actions = investigation.get("recommended_actions") or []
    if actions:
        lines.append("## 处置建议（按优先级）")
        lines.append("")
        for i, act in enumerate(actions, 1):
            lines.append(f"{i}. {act}")
        lines.append("")

    if evidence:
        lines.append("## 附录：原始证据日志")
        lines.append("")
        lines.append(f"_共 {len(evidence)} 条相关日志，按时间倒序。_")
        lines.append("")
        for hit in evidence:
            ts = hit.get("@timestamp") or "?"
            doc_id = hit.get("_id") or ""
            lines.append(f"### `{ts}` — `_id = {doc_id}`")
            lines.append("")
            lines.append("```json")
            try:
                import json as _json
                lines.append(_json.dumps(hit.get("_source", {}), ensure_ascii=False, indent=2))
            except Exception:
                lines.append(str(hit.get("_source", {})))
            lines.append("```")
            lines.append("")

    lines.append("---")
    lines.append("_由 RST Elastic AI Copilot 自动生成。请人工复核后再作为正式交付物。_")

    return "\n".join(lines)


def _md_cell(s: Any) -> str:
    text = "" if s is None else str(s)
    return text.replace("|", "\\|").replace("\n", " ")
