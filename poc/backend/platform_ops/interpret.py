"""Platform health interpretation: turn `checks.run_all()`'s deterministic
report into a model-generated cross-check synthesis.

checks.py already gives every check a correct, standalone Chinese summary/
advice — that's on the operator's screen already. What a rule engine can't
do is connect the dots across checks (disk full -> index went read-only ->
writes fail -> data stream goes stale look like four separate symptoms but
are one incident) or fold in the customer's own KB context (a data stream
being "stale" means something different if the KB says that source's agent
box is off on weekends). This module is that layer, following the same
"LLM call + RAG + parse + degrade" shape as explain.py's `_run`.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import prompts
from ..llm import parse_json
from ..llm_router import get_router
from ..rag import augment_prompt_meta

logger = logging.getLogger("rst.platform_ops.interpret")

_OK = "ok"
_VERDICT_ORDER = {"fail": 0, "warn": 1, "unknown": 2, "ok": 3}

_RETRIEVAL_QUERY_MAX = 500
_ACTIONS_MAX = 5
_CONCLUSION_MAX = 300
_TITLE_MAX = 80
_WHY_MAX = 300
_HOW_MAX = 500


async def interpret(report: dict[str, Any]) -> dict[str, Any]:
    """Cross-check synthesis for a platform health report.

    Healthy cluster (no fail/warn/unknown) short-circuits before the LLM
    call entirely — there is nothing to synthesize and no reason to spend a
    token on it.
    """
    problem_checks = [c for c in report.get("checks", []) if c.get("verdict") != _OK]
    if not problem_checks:
        return {
            "conclusion": "各项检查正常，未发现需要处理的问题。",
            "actions": [],
            "degraded": False,
            "rag_chunks_used": 0,
        }

    user_prompt = _build_user_prompt(report)
    retrieval_query = _build_retrieval_query(problem_checks)
    user_prompt, rag_used = await augment_prompt_meta(
        user_prompt, top_k=3, retrieval_query=retrieval_query
    )

    # SEC-CC-1: resolve the sealed prompt BEFORE the try below. Inside it,
    # FeatureLocked would be swallowed as "the model failed" and the caller
    # would get a degraded fallback instead of the 403 it must see.
    system_prompt = prompts.platform_interpret_system_prompt()

    raw = ""
    try:
        resp, _provider = await get_router().chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            reasoning="low",  # 解读平台指标：有固定 JSON 格式
        )
        if not resp.choices:
            raise ValueError("model returned no choices")
        raw = resp.choices[0].message.content or ""
        result = _normalize(parse_json(raw))
        result["degraded"] = False
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "platform interpret LLM call/output failed (%s); raw output (first 1500 chars): %s",
            e, raw[:1500],
        )
        result = _fallback(problem_checks)
        result["degraded"] = True
    result["rag_chunks_used"] = rag_used
    return result


def _build_user_prompt(report: dict[str, Any]) -> str:
    import json as _json

    return (
        "以下是平台自动体检报告（JSON），counts 是各 verdict 的数量统计，"
        "checks 是逐项结果（每项已有中文 summary/advice）：\n\n"
        f"{_json.dumps(report, ensure_ascii=False, indent=2)}\n\n"
        "请按系统提示的 JSON 格式输出综合结论与行动清单。"
    )


def _build_retrieval_query(problem_checks: list[dict[str, Any]]) -> str:
    # Retrieval must target the actual problem, not our own prompt boilerplate
    # — same rationale as llm.generate_dsl's retrieval_query. ok checks add
    # no signal here, so only fail/warn/unknown items contribute.
    parts = [f"{c.get('title', '')} {c.get('summary', '')}" for c in problem_checks]
    return " ".join(parts)[:_RETRIEVAL_QUERY_MAX]


def _fallback(problem_checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Degrade path must still be useful, not an empty shell: build the
    conclusion/actions straight from the checks' own deterministic fields,
    ordered fail-first."""
    ordered = sorted(problem_checks, key=lambda c: _VERDICT_ORDER.get(c.get("verdict"), 9))
    n_fail = sum(1 for c in problem_checks if c.get("verdict") == "fail")
    n_warn = sum(1 for c in problem_checks if c.get("verdict") == "warn")
    conclusion = f"发现 {n_fail} 项异常、{n_warn} 项需注意，详见下方各项结论。"

    actions = []
    for c in ordered[:_ACTIONS_MAX]:
        actions.append({
            "title": c.get("title", ""),
            "why": c.get("summary", ""),
            "how": c.get("advice", "") or "请参考上方检查详情自行核实。",
        })

    return _normalize({"conclusion": conclusion, "actions": actions})


def _normalize(payload: dict[str, Any]) -> dict[str, Any]:
    """Defensive truncation — mirrors explain.py's `_normalize` so a
    misbehaving model (or an oversized fallback) can't blow up the UI."""
    out: dict[str, Any] = {
        "conclusion": _clip(payload.get("conclusion", ""), _CONCLUSION_MAX),
        "actions": [],
    }

    actions = payload.get("actions")
    if isinstance(actions, list):
        for item in actions[:_ACTIONS_MAX]:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            if not title:
                continue
            out["actions"].append({
                "title": _clip(str(title), _TITLE_MAX),
                "why": _clip(str(item.get("why", "") or ""), _WHY_MAX),
                "how": _clip(str(item.get("how", "") or ""), _HOW_MAX),
            })

    return out


def _clip(s: Any, max_len: int) -> str:
    s = "" if s is None else str(s)
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"
