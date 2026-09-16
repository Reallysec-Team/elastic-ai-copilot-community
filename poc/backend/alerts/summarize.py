"""One-sentence AI summary of an alert, generated at ingest.

Default ON (disable with RST_ALERT_SUMMARY=0). Best-effort: any LLM failure
returns "" and the alert is stored without a summary — never blocks ingest.

The alert is field-masked before it reaches the LLM (external in cloud mode), so
the summary describes masked entities (e.g. "内网主机遭暴力破解"), honouring the
no-raw-egress rule. Airgapped mode passes values through.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ..field_masking import mask_doc
from ..llm_router import get_router

logger = logging.getLogger("rst.alerts.summarize")

_SYSTEM = (
    "你是安全运营分析助手。用一句简体中文（不超过 30 字）概括该告警事件："
    "点明攻击类型/行为、涉及主体与目标，直述结论，不要复述字段名、不加前缀。"
)
_SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]


def _enabled() -> bool:
    return (os.environ.get("RST_ALERT_SUMMARY", "1").strip().lower()
            not in ("0", "false", "no", "off"))


def _min_severity_ok(severity: str) -> bool:
    """Optional floor: RST_ALERT_SUMMARY_MIN_SEVERITY (default info = summarize all)."""
    floor = (os.environ.get("RST_ALERT_SUMMARY_MIN_SEVERITY", "info") or "info").lower()
    try:
        return _SEVERITY_ORDER.index((severity or "info").lower()) >= _SEVERITY_ORDER.index(floor)
    except ValueError:
        return True


def _payload(alert: dict[str, Any]) -> dict[str, Any]:
    """Compact masked view for the prompt — rule + subject + a slim raw slice."""
    safe = mask_doc(alert)
    raw = safe.get("raw") or {}
    # keep only a few common signal fields from raw to bound tokens
    slim = {k: raw[k] for k in (
        "kibana.alert.rule.description", "signal.rule.description",
        "event.action", "event.category", "message",
        "source.ip", "destination.ip", "user.name", "host.name",
    ) if isinstance(raw, dict) and raw.get(k) not in (None, "", [])}
    return {
        "rule_name": safe.get("rule_name"),
        "severity": safe.get("severity"),
        "subject": f"{safe.get('subject_field') or ''}={safe.get('subject_value') or ''}".strip("="),
        "signal": slim,
    }


async def summarize(alert: dict[str, Any]) -> str:
    """Return a one-sentence summary, or "" (disabled / below floor / LLM error)."""
    if not _enabled() or not _min_severity_ok(alert.get("severity", "info")):
        return ""
    import json
    try:
        resp, _ = await get_router().chat_completion(
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": json.dumps(_payload(alert), ensure_ascii=False)},
            ],
            temperature=0,
            reasoning="none",  # 一句话摘要
            max_tokens=80,
        )
        text = (resp.choices[0].message.content or "").strip()
        # collapse whitespace / drop any stray quotes; hard cap length
        text = " ".join(text.split()).strip('"“”')
        return text[:80]
    except Exception as e:  # noqa: BLE001 — best-effort, never block ingest
        logger.warning("alert_summarize_failed", extra={"error": str(e)})
        return ""
