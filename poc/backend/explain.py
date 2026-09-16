"""Log explanation: take a single log document, return structured analysis.

Reuses the same Volcengine Ark client as DSL generation but with a different
system prompt focused on log interpretation. Returns a normalized structured
shape so the frontend can rely on fields existing.
"""

import logging
from typing import Any

from .field_masking import mask_aggregations, mask_doc
from .llm import parse_json
from .llm_router import get_router
from .prompts import (
    build_explain_prompt,
    build_explain_result_prompt,
    explain_result_system_prompt,
    explain_system_prompt,
)
from .rag import augment_prompt_meta

logger = logging.getLogger("rst.explain")

_VALID_SEVERITY = {"info", "low", "medium", "high", "critical"}
_VALID_CONFIDENCE = {"low", "medium", "high"}


async def explain_log(doc: dict[str, Any], index: str | None = None) -> dict[str, Any]:
    """Generate a structured explanation for a single log document."""
    masked_doc = mask_doc(doc)
    user_prompt = build_explain_prompt(masked_doc, index)
    return await _run(
        explain_system_prompt(),
        user_prompt,
        fallback="模型本次输出无法解析,未能生成日志解读。请重试,或换一条日志再试。",
    )


async def explain_result(
    question: str,
    dsl: dict[str, Any],
    aggregations: dict[str, Any] | None = None,
    sample_hits: list[dict[str, Any]] | None = None,
    total: int | None = None,
    index: str | None = None,
) -> dict[str, Any]:
    """Interpret a whole query RESULT SET (aggregations + sample hits).

    A `size:0` aggregation query renders as a bare table of numbers — correct,
    but a dead end for anyone who isn't already an ES analyst. This turns it
    into 结论 + 可信度 + 下一步, reusing the explain output shape so the same
    dialog renders it. Subject values are masked exactly like everywhere else
    before the model sees them.
    """
    # mask_aggregations needs the request aggs spec for field provenance —
    # bucket keys are masked according to the field each terms/histogram is on.
    req_aggs = dsl.get("aggs") or dsl.get("aggregations") or {}
    masked_aggs = mask_aggregations(aggregations, req_aggs) if aggregations else None
    masked_hits = [mask_doc(h) for h in (sample_hits or [])[:5]]
    user_prompt = build_explain_result_prompt(
        question, dsl, masked_aggs, masked_hits, total, index
    )
    return await _run(
        explain_result_system_prompt(),
        user_prompt,
        fallback="模型本次输出无法解析,未能生成结果解读。请重试。",
    )


async def _run(system: str, user_prompt: str, fallback: str) -> dict[str, Any]:
    """Shared LLM call + normalize + degrade path for both explain flavours.

    Best-effort: a provider outage/timeout or an empty/unparseable LLM reply
    must not 500 (and with temperature=0 a retry would just reproduce it).
    Degrade to a structurally-valid result flagged `degraded=true` so the UI
    still renders. The raw model output stays in the server log only — never
    in the response. The provider call is INSIDE the try so a transport error
    degrades the same way an unparseable reply does.
    """
    user_prompt, rag_used = await augment_prompt_meta(user_prompt, top_k=3)
    raw = ""
    try:
        resp, _provider = await get_router().chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            reasoning="none",  # 解释结果：写几段话，不推理
        )
        if not resp.choices:
            raise ValueError("model returned no choices")
        raw = resp.choices[0].message.content or ""
        result = _normalize(parse_json(raw))
        result["degraded"] = False
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "explain LLM call/output failed (%s); raw output (first 1500 chars): %s",
            e, raw[:1500],
        )
        result = _normalize({})
        result["degraded"] = True
        result["summary"] = fallback
    result["rag_chunks_used"] = rag_used
    return result


def _normalize(payload: dict[str, Any]) -> dict[str, Any]:
    """Defensive normalization — guarantee the frontend's expected shape.

    Trims runaway strings (cap at 2000 chars per text field, 12 entries per list)
    so a misbehaving model can't blow up the modal.
    """
    out: dict[str, Any] = {
        "summary": _clip(payload.get("summary", ""), 600),
        "log_type": _clip(payload.get("log_type", "unknown") or "unknown", 80),
        "key_fields": [],
        "indicators": [],
        "investigation": [],
        "severity": "info",
        "confidence": "medium",
    }

    kf = payload.get("key_fields")
    if isinstance(kf, list):
        for item in kf[:12]:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            out["key_fields"].append({
                "name": _clip(str(name), 100),
                "value": _clip("" if item.get("value") is None else str(item.get("value")), 200),
                "why": _clip(str(item.get("why", "") or ""), 300),
            })

    for k in ("indicators", "investigation"):
        v = payload.get(k)
        if isinstance(v, list):
            out[k] = [_clip(str(x), 300) for x in v[:8] if x is not None and str(x).strip()]

    sev = payload.get("severity")
    if isinstance(sev, str) and sev in _VALID_SEVERITY:
        out["severity"] = sev

    conf = payload.get("confidence")
    if isinstance(conf, str) and conf in _VALID_CONFIDENCE:
        out["confidence"] = conf

    return out


def _clip(s: Any, max_len: int) -> str:
    s = "" if s is None else str(s)
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"
