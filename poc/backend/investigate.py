"""Alert investigation: take an alert document, gather context from ES, ask LLM
for a SOC-style structured analysis (timeline, attack chain, MITRE mapping,
recommendations).
"""

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from .enrich.prompt_context import asset_context_block
from .es_client import get_es
from .field_masking import mask_doc
from .llm import parse_json
from . import llm_reasoning
from .llm_router import get_router
from .prompts import investigate_system_prompt, build_investigate_prompt
from .rag import augment_prompt_meta

logger = logging.getLogger("rst.investigate")

# Optional per-stage progress callback for the SSE streaming endpoint. When None
# (the default non-streaming callers), every emit is a no-op — behaviour is
# unchanged. Event shape: {"type":"stage","key","label","status","detail"?}.
ProgressCb = Callable[[dict[str, Any]], Awaitable[None]] | None


async def emit_stage(
    progress: ProgressCb, key: str, label: str, status: str, detail: str | None = None
) -> None:
    """Push one pipeline-stage marker to the progress sink, if any. Best-effort:
    a failing sink (client gone) must never break the investigation itself."""
    if progress is None:
        return
    evt: dict[str, Any] = {"type": "stage", "key": key, "label": label, "status": status}
    if detail is not None:
        evt["detail"] = detail
    try:
        await progress(evt)
    except Exception as e:  # noqa: BLE001
        logger.debug("progress emit failed (%s); ignoring", e)


_VALID_SEVERITY = {"info", "low", "medium", "high", "critical"}
_VALID_CONFIDENCE = {"low", "medium", "high"}

# Heuristic — find a "subject" entity to query for related logs.
_SUBJECT_FIELDS = [
    "clientip", "client.ip", "source.ip", "src_ip", "ip",
    "user.name", "username", "user_name",
    "host.name", "hostname", "host", "agent.hostname",
]


async def investigate_alert(
    alert: dict[str, Any], index: str, window_minutes: int = 30,
    progress: ProgressCb = None,
    reasoning: str | None = None,
) -> dict[str, Any]:
    """Investigate an alert: gather context, call LLM, normalize output.

    `progress`, when given, receives a stage marker between each pipeline step so
    the SSE endpoint can render a live checklist; None (the default) is a no-op.
    """
    alert_src = alert.get("_source") if isinstance(alert, dict) and "_source" in alert else alert
    if not isinstance(alert_src, dict):
        alert_src = {}

    await emit_stage(progress, "context", "拉取告警上下文", "active")
    context = await _gather_context(alert_src, index, window_minutes)
    await emit_stage(progress, "context", "拉取告警上下文", "done", f"{len(context)} 条")

    # Apply field masking based on license tier (cloud / private / airgapped).
    # `_gather_context` runs against ES with full data; only the LLM payload is masked.
    masked_alert = mask_doc(alert_src)
    masked_context = [
        {"_id": h.get("_id"), "_source": mask_doc(h.get("_source", {}))}
        for h in context
    ]

    user_prompt = build_investigate_prompt(masked_alert, masked_context, index)
    await emit_stage(progress, "enrich", "资产/身份富化", "active")
    block = await asset_context_block(alert_src)
    await emit_stage(progress, "enrich", "资产/身份富化", "done")
    if block:
        user_prompt = f"资产语境:\n{block}\n\n{user_prompt}"
    await emit_stage(progress, "rag", "知识库检索", "active")
    user_prompt, rag_used = await augment_prompt_meta(user_prompt, top_k=5)
    await emit_stage(progress, "rag", "知识库检索", "done", f"{rag_used} 段")
    await emit_stage(progress, "analyze", "AI 分析中", "active")
    # Best-effort: a provider outage/timeout or an empty/unparseable LLM reply
    # must not 500 (and with temperature=0 a retry would just reproduce it).
    # Degrade to a structurally-valid result flagged `degraded=true` so the UI
    # still renders. The raw model output stays in the server log only — never
    # in the response. The provider call is INSIDE the try so a transport error
    # degrades the same way an unparseable reply does.
    # SEC-CC-1: resolve the sealed prompt BEFORE the try — inside it,
    # FeatureLocked would be swallowed into a "degraded" result instead of
    # surfacing as the 403 an unentitled host must see.
    system_prompt = investigate_system_prompt()

    raw = ""
    try:
        resp, _provider = await get_router().chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            reasoning=llm_reasoning.from_request(reasoning, "high"),  # 告警调查：付费引擎
        )
        if not resp.choices:
            raise ValueError("model returned no choices")
        raw = resp.choices[0].message.content or ""
        payload = parse_json(raw)
        result = _normalize(payload, len(context))
        result["degraded"] = False
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "investigate LLM call/output failed (%s); raw output (first 1500 chars): %s",
            e, raw[:1500],
        )
        result = _degraded_result(len(context))
    result["rag_chunks_used"] = rag_used
    return result


def _degraded_result(context_count: int) -> dict[str, Any]:
    """Structurally-valid fallback when the LLM output can't be parsed.

    Mirrors `_normalize`'s shape so the frontend renders normally. Carries no
    raw model output — only a generic, user-facing explanation.
    """
    result = _normalize({}, context_count)
    result["degraded"] = True
    result["summary"] = "模型本次输出无法解析,未能生成调查结论。请重试,或换一条告警再试。"
    return result


async def _gather_context(
    alert_src: dict[str, Any], index: str, window_minutes: int, top_n: int = 12
) -> list[dict[str, Any]]:
    """Pull related logs around the alert subject + time. Best-effort; tolerant of failures."""
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
    time_filter = {"range": {"@timestamp": _time_bounds(alert_src, window_minutes)}}

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
                    "size": top_n,
                    "sort": [{"@timestamp": "desc"}],
                },
            )
            hits = (resp.body.get("hits") or {}).get("hits") or []
            return [
                {"_id": h.get("_id"), "_source": h.get("_source", {})}
                for h in hits
            ]
        except Exception as e:
            logger.debug(f"context query failed for {fld_variant}: {e}")
            continue
    return []


_TS_FIELDS = ["@timestamp", "timestamp", "event.created", "event.ingested", "time"]


def _time_bounds(alert_src: dict[str, Any], window_minutes: int) -> dict[str, str]:
    """Context time range, anchored on the ALERT'S OWN timestamp (event time) —
    a symmetric ±window around when it happened — not `now`. Investigating a
    historical alert must gather logs from *that* period; anchoring on `now`
    silently returns nothing whenever the data is older than the window (the
    single biggest cause of empty investigation context). Falls back to
    `now-window` only when the alert carries no parseable timestamp."""
    raw = None
    for f in _TS_FIELDS:
        v = _get_nested(alert_src, f)
        if v is not None and str(v).strip():
            raw = str(v).strip()
            break
    if raw:
        try:
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            lo = (ts - timedelta(minutes=window_minutes)).isoformat()
            hi = (ts + timedelta(minutes=window_minutes)).isoformat()
            return {"gte": lo, "lte": hi}
        except (ValueError, TypeError):
            logger.debug("unparseable alert timestamp %r; falling back to now-window", raw)
    return {"gte": f"now-{window_minutes}m"}


def _get_nested(obj: dict[str, Any], path: str) -> Any:
    cur: Any = obj
    for p in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


# 时间线里的 time 会被 ES 当日期字段。模型有时写的是一个区间
# （"2026-09-05T23:49:17Z ~ 23:50:05Z"），整条记录会被 ES 以
# document_parsing_exception 拒掉 —— 结果照常显示，归档却静悄悄地没了。
_ISO_PREFIX = re.compile(
    r"^\s*(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)"
)


def _split_timeline_time(raw: object) -> tuple[str, str]:
    """(能当日期用的那一段, 剩下的说明文字)。

    认不出日期就整串当说明文字返回，时间留空 —— 空串 ES 收得下，非日期字符串收不下。
    """
    text = str(raw or "").strip()
    if not text:
        return "", ""
    m = _ISO_PREFIX.match(text)
    if not m:
        return "", _clip(text, 80)
    ts = m.group(1)
    rest = text[m.end():].strip(" \t~-–—>至到")
    return ts, _clip(rest, 80)


def _normalize(payload: dict[str, Any], context_count: int) -> dict[str, Any]:
    out: dict[str, Any] = {
        "summary": _clip(payload.get("summary"), 600),
        "alert_type": _clip(payload.get("alert_type") or "unknown", 80),
        "severity": "info",
        "is_likely_false_positive": bool(payload.get("is_likely_false_positive", False)),
        "false_positive_reason": _clip(payload.get("false_positive_reason") or "", 400),
        "timeline": [],
        "attack_chain": [],
        "mitre_techniques": [],
        "affected_assets": [],
        "recommended_actions": [],
        "confidence": "medium",
        "context_count": context_count,
    }

    sev = payload.get("severity")
    if isinstance(sev, str) and sev in _VALID_SEVERITY:
        out["severity"] = sev
    conf = payload.get("confidence")
    if isinstance(conf, str) and conf in _VALID_CONFIDENCE:
        out["confidence"] = conf

    tl = payload.get("timeline")
    if isinstance(tl, list):
        for item in tl[:8]:
            if isinstance(item, dict):
                ts, extra = _split_timeline_time(item.get("time", ""))
                event = _clip(item.get("event", ""), 300)
                if extra:
                    # 「23:49:17Z ~ 23:50:05Z」这种区间：前半截当时间，后半截并进
                    # 事件描述，免得为了让 ES 收下就把信息丢了。
                    event = _clip(f"（{extra}）{event}", 300)
                out["timeline"].append({"time": ts, "event": event})

    ac = payload.get("attack_chain")
    if isinstance(ac, list):
        for item in ac[:8]:
            if isinstance(item, dict):
                out["attack_chain"].append({
                    "phase": _clip(item.get("phase", ""), 80),
                    "evidence": _clip(item.get("evidence", ""), 400),
                })

    mt = payload.get("mitre_techniques")
    if isinstance(mt, list):
        for item in mt[:10]:
            if isinstance(item, dict):
                out["mitre_techniques"].append({
                    "id": _clip(item.get("id", ""), 20),
                    "name": _clip(item.get("name", ""), 80),
                    "evidence": _clip(item.get("evidence", ""), 300),
                })

    aa = payload.get("affected_assets")
    if isinstance(aa, list):
        for item in aa[:10]:
            if isinstance(item, dict):
                out["affected_assets"].append({
                    "type": _clip(item.get("type", ""), 20),
                    "id": _clip(item.get("id", ""), 200),
                })

    ra = payload.get("recommended_actions")
    if isinstance(ra, list):
        out["recommended_actions"] = [
            _clip(str(x), 300) for x in ra[:6] if x is not None and str(x).strip()
        ]

    return out


def _clip(s: Any, max_len: int) -> str:
    s = "" if s is None else str(s)
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"
