"""Agentic alert investigation — ReAct-style tool-use loop.

Where `investigate.py` runs ONE fixed context query then ONE LLM call, this
lets the LLM drive ES exploration itself: it calls the `es_search` tool as many
times as it needs (bounded), sees masked results, and iterates until it emits a
final structured verdict or hits the step cap.

Output shape is identical to `investigate_alert` (reuses `_normalize` /
`_degraded_result`) plus three agentic fields: `agentic=True`, `agentic_steps`,
and `tool_trace` (per-call {tool,args,hit_count,error} for the UI/audit).

Guardrails (defence in depth — same as the /api/execute path, applied to EVERY
tool call the model makes):
  - index whitelist  (index_whitelist.is_allowed)
  - DSL validator    (validate_dsl — blocks script/update/delete, caps size)
  - per-call size cap (RST_AGENTIC_SIZE_CAP, dsl.size clamped)
  - step cap          (RST_AGENTIC_MAX_STEPS, then one forced tool-less final)
  - field masking     (mask_doc on every returned _source)

Aggregations ARE returned, masked via the request aggs spec (field_masking.
mask_aggregations): bucket keys get the same per-field tier policy as documents,
counts/metrics survive, unknown-provenance keys are defensively masked.

Feature-flagged: `RST_AGENTIC_INVESTIGATE`. When off, callers use
`investigate_alert`. This module never installs itself — the route chooses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from copy import deepcopy
from typing import Any

from . import index_whitelist
from .enrich.prompt_context import asset_context_block
from .es_client import execute_search, friendly_es_error
from .field_masking import _mask_ip, current_mode, mask_aggregations, mask_doc
from .investigate import (
    ProgressCb,
    _degraded_result,
    _gather_context,
    _normalize,
    _time_bounds,
    emit_stage,
    investigate_alert,
)
from .llm import parse_json
from .llm_router import get_router
from . import feature_unlock, llm_reasoning
from .prompts import agentic_investigate_system_prompt, build_agentic_investigate_prompt
from .validator import apply_default_sort, validate_dsl

logger = logging.getLogger("rst.agentic_investigate")

FEATURE = "alert_investigation"


def _core() -> dict:
    """SEC-CC-1 sealed core: the analyst prompts and the tool schema the agent
    is handed. Raises FeatureLocked on an unentitled host."""
    return feature_unlock.load_premium(FEATURE)

_DEFAULT_MAX_STEPS = 6
_DEFAULT_SIZE_CAP = 20


def agentic_enabled() -> bool:
    """Whether /api/investigate-alert uses the agentic loop. Default ON — the
    richer multi-round investigation is the intended product behaviour. Turn OFF
    explicitly with RST_AGENTIC_INVESTIGATE=0 (single-step legacy path). A
    provider without function-calling auto-falls-back to single-step regardless."""
    v = os.environ.get("RST_AGENTIC_INVESTIGATE", "").strip().lower()
    return v not in ("0", "false", "no", "off")


def _bounded_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(os.environ.get(name, "").strip())
    except (TypeError, ValueError):
        return default
    return v if lo <= v <= hi else default


def _max_steps() -> int:
    return _bounded_int("RST_AGENTIC_MAX_STEPS", _DEFAULT_MAX_STEPS, 1, 20)


def _size_cap() -> int:
    return _bounded_int("RST_AGENTIC_SIZE_CAP", _DEFAULT_SIZE_CAP, 1, 200)


def _token_budget() -> int:
    """Soft cap on cumulative total_tokens across the loop. 0 = disabled.
    When exceeded after a step, we stop searching and force a final verdict —
    bounds cost on a model that would otherwise keep drilling."""
    return _bounded_int("RST_AGENTIC_TOKEN_BUDGET", 0, 0, 10_000_000)


_DEFAULT_DEADLINE_S = 180.0


def _deadline_s() -> float:
    """Overall wall-clock budget for the whole loop. On timeout the investigation
    degrades gracefully instead of hanging the request. Defaults to 180s so an
    always-on agentic loop can't run the full step-cap * provider-timeout worst
    case; set RST_AGENTIC_DEADLINE_S=0 to disable, or a number to override."""
    raw = os.environ.get("RST_AGENTIC_DEADLINE_S", "").strip()
    if not raw:
        return _DEFAULT_DEADLINE_S
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_DEADLINE_S
    return v if v > 0 else 0.0


def _usage_tokens(resp: Any) -> int:
    u = getattr(resp, "usage", None)
    if u is None:
        return 0
    return getattr(u, "total_tokens", 0) or 0


def _unwrap(alert: Any) -> dict[str, Any]:
    src = alert.get("_source") if isinstance(alert, dict) and "_source" in alert else alert
    return src if isinstance(src, dict) else {}


def _tc_name(tc: Any) -> str:
    return tc.function.name


def _tc_args_raw(tc: Any) -> str:
    return tc.function.arguments or ""


def _assistant_msg(msg: Any) -> dict[str, Any]:
    """Serialize the model's tool-call turn back into a request message so the
    next round has the full conversation (assistant tool_calls + tool results)."""
    return {
        "role": "assistant",
        "content": msg.content or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": _tc_name(tc), "arguments": _tc_args_raw(tc)},
            }
            for tc in msg.tool_calls
        ],
    }


def _parse_tool_args(raw: str) -> Any:
    """Parse a tool call's `arguments` string, tolerating two things models do.

    Observed live (6-round agentic run, 2 rounds burned): the model wrapped the
    JSON in a ```json fence, and once emitted a sentence before the object. Both
    are recoverable without another model round-trip — and a round-trip here is
    not free: the step cap is small, so two bad parses can eat a third of the
    investigation.

    Returns the parsed value, or None when nothing JSON-shaped is in there. The
    caller still rejects non-dict results, so a bare list/string parses here and
    is refused there with the clearer message.
    """
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass

    # ```json … ``` (or a bare ``` fence)
    if text.startswith("```"):
        body = text[3:]
        if body[:4].lower().startswith("json"):
            body = body[4:]
        end = body.rfind("```")
        if end != -1:
            body = body[:end]
        try:
            return json.loads(body.strip())
        except (ValueError, TypeError):
            pass

    # Prose around the object: take the outermost {...}.
    lo, hi = text.find("{"), text.rfind("}")
    if lo != -1 and hi > lo:
        try:
            return json.loads(text[lo : hi + 1])
        except (ValueError, TypeError):
            pass

    # A complete object followed by junk. Seen live: 379 chars where the streamed
    # `arguments` repeated a slice of its own middle after the closing brace —
    # `loads` rejects the lot, `raw_decode` reads the first object and stops.
    # The first object is the one the model meant; the tail is accumulation debris.
    if lo != -1:
        try:
            value, _end = json.JSONDecoder().raw_decode(text[lo:])
            return value
        except (ValueError, TypeError):
            pass
    return None


_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# A masked IP placeholder filling a whole DSL value: '172.19.x.x' (cloud) / '172.19.170.x' (private).
_MASKED_IP = re.compile(r"^(?:\d{1,3}\.\d{1,3}\.x\.x|\d{1,3}\.\d{1,3}\.\d{1,3}\.x)$")
# Any residual masked placeholder left after resolution — masked IP tail or the *** token.
_MASKED_RESIDUAL = re.compile(r"\d\.x\.x|\d{1,3}\.\d{1,3}\.\d{1,3}\.x|\*\*\*")
_UNMASK_MAX_CANDIDATES = 8
_UNMASK_ERR = (
    "DSL 里用了脱敏占位值（含 x.x / ***）。脱敏值不能当过滤条件，否则查不到数据："
    "证据里出现过的 IP 可原样写进 term/terms（服务端会还原真实值）；"
    "其它请改用未脱敏字段（规则名 / 类别 / 时间范围 / 文档 _id）过滤。"
)


def _iter_strings(node: Any):
    """Every string leaf in a nested dict/list — REAL rows to learn from, or DSL to scan."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _iter_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_strings(v)


def _learn_ips(hits: list[dict[str, Any]], unmask: dict[str, set[str]]) -> None:
    """Remember masked → real for every IPv4 in REAL hits, so the model's pivot on a
    masked IP it saw in evidence can be resolved server-side (model never sees this)."""
    mode = current_mode()
    for h in hits:
        for s in _iter_strings(h.get("_source", h)):
            for ip in _IPV4.findall(s):
                m = _mask_ip(ip, mode)
                if m != ip:
                    unmask.setdefault(m, set()).add(ip)


def _resolve_masked(
    dsl: dict[str, Any], unmask: dict[str, set[str]]
) -> tuple[dict[str, Any], str | None]:
    """Rewrite masked IP literals in the DSL back to the real values seen in evidence.
    Unique → substitution anywhere; ambiguous `{"term": {f: mask}}` → `{"terms": {f: [reals]}}`
    (≤8 candidates); unseen / too-many → left masked and refused. Returns (dsl, error)."""
    def _rw(node: Any) -> Any:
        if isinstance(node, dict):
            # `{"term": {field: 'mask'}}` with several candidates → promote to a terms list.
            if set(node) == {"term"} and isinstance(node["term"], dict) and len(node["term"]) == 1:
                (field, val), = node["term"].items()
                if isinstance(val, str) and _MASKED_IP.match(val):
                    reals = sorted(unmask.get(val) or ())
                    if len(reals) == 1:
                        return {"term": {field: reals[0]}}
                    if 1 < len(reals) <= _UNMASK_MAX_CANDIDATES:
                        return {"terms": {field: reals}}
            return {k: _rw(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_rw(v) for v in node]
        if isinstance(node, str) and _MASKED_IP.match(node):
            reals = sorted(unmask.get(node) or ())
            if len(reals) == 1:  # unique → plain substitution, anywhere in the DSL
                return reals[0]
        # ponytail: ambiguous masks outside the bare `term` shape stay masked → refused
        # below, same as QAC (only `col = 'mask'` expands to IN). Promote elsewhere if needed.
        return node

    resolved = _rw(deepcopy(dsl))
    if any(_MASKED_RESIDUAL.search(s) for s in _iter_strings(resolved)):
        return resolved, _UNMASK_ERR
    return resolved, None


async def _run_tool(
    tc: Any, wl: Any, size_cap: int, unmask: dict[str, set[str]] | None = None
) -> tuple[dict[str, Any], int]:
    """Execute one model tool call under all guardrails. Returns (tool_output,
    hits_returned). Errors are returned AS DATA (not raised) so the model can
    read the failure and adjust — a bad query shouldn't abort the investigation."""
    name = _tc_name(tc)
    if name != "es_search":
        return {"error": f"unknown tool '{name}'"}, 0

    args = _parse_tool_args(_tc_args_raw(tc))
    if args is None:
        return {"error": "tool arguments are not valid JSON"}, 0
    if not isinstance(args, dict):
        return {"error": "tool arguments must be a JSON object"}, 0

    idx = args.get("index")
    dsl = args.get("dsl")
    if not isinstance(idx, str) or not idx.strip():
        return {"error": "es_search requires a string 'index'"}, 0
    if not isinstance(dsl, dict):
        return {"error": "es_search requires an object 'dsl'"}, 0

    # 白名单为空时 is_allowed 恒真，所以自有索引要单独挡一次 —— 告警字段里
    # 挟带的指令否则能把 es_search 指向产品自己的存储。
    owned_hit = index_whitelist.blocked_owned(idx)
    if owned_hit or not wl.is_allowed(idx):
        return {"error": f"index '{idx}' 不在授权白名单内，已拒绝"}, 0

    # 先钳 size 再校验：`validate_dsl` 现在也管命中数上限，而这一层的 size_cap
    # （默认 20）比它严得多。顺序反过来的话，模型写一个 size: 9999 会被校验直接
    # 拒掉并把错误回给模型，而这条钳位本来就是为了「随它写，网关按自己的上限来」。
    size = dsl.get("size")
    if not isinstance(size, int) or size <= 0 or size > size_cap:
        dsl = {**dsl, "size": size_cap}

    # A masked value ('172.19.x.x', 's***p') copied out of the evidence into a filter
    # matches nothing in cloud/private masking. Resolve IPs we have seen the real value
    # of; otherwise refuse with guidance, don't waste the round.
    dsl, err = _resolve_masked(dsl, unmask or {})
    if err:
        return {"error": err}, 0

    try:
        validate_dsl(dsl)
    except ValueError as e:
        return {"error": f"DSL 非法：{e}"}, 0

    try:
        body = await execute_search(idx, apply_default_sort(dsl))
    except Exception as e:  # noqa: BLE001 — surface a friendly error to the model
        _status, friendly = friendly_es_error(e)
        return {"error": friendly}, 0

    hits = ((body.get("hits") or {}).get("hits")) or []
    hits = hits[:size_cap]
    if unmask is not None:
        _learn_ips(hits, unmask)  # learn from REAL hits before masking
    masked = [
        {"_id": h.get("_id"), "_source": mask_doc(h.get("_source", {}))}
        for h in hits
    ]
    out: dict[str, Any] = {"hits": masked, "hit_count": len(masked)}
    # Aggregations are masked via the request aggs spec (field provenance) so
    # counts/stats survive while identifying bucket keys are masked — same tier
    # policy as documents. Unknown-provenance keys are defensively masked.
    aggs = body.get("aggregations")
    if isinstance(aggs, dict) and aggs:
        req_aggs = dsl.get("aggs") or dsl.get("aggregations") or {}
        out["aggregations"] = mask_aggregations(aggs, req_aggs)
    return out, len(masked)


def _finalize(content: str, hits_seen: int, trace: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        payload = parse_json(content or "")
        result = _normalize(payload, hits_seen)
        result["degraded"] = False
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "agentic final parse failed (%s); raw (first 1500): %s",
            e, (content or "")[:1500],
        )
        result = _degraded_result(hits_seen)
    result["agentic"] = True
    result["agentic_steps"] = len(trace)
    result["tool_trace"] = trace
    return result


def _timeout_result() -> dict[str, Any]:
    result = _degraded_result(0)
    result["degraded"] = True
    result["agentic"] = True
    result["agentic_steps"] = 0
    result["tool_trace"] = []
    result["summary"] = (
        "调查超时(agentic 检索超过时限),已中止。请重试,或改用非 agentic 模式。"
    )
    return result


async def agentic_investigate_alert(
    alert: dict[str, Any],
    index: str,
    window_minutes: int = 30,
    max_steps: int | None = None,
    progress: ProgressCb = None,
    reasoning: str | None = None,
) -> dict[str, Any]:
    """Investigate an alert via an LLM-driven es_search tool loop.

    Hardening: overall wall-clock deadline (degrade on timeout), cumulative
    token budget (early final), and — if the provider can't do function-calling
    at all (first call raises) — a graceful fallback to the single-step
    investigate_alert path so a non-tool model still yields a verdict.

    `progress` (SSE endpoint only) receives coarse stage markers — asset enrich,
    an updating retrieve line, then AI synthesis. None is a no-op.
    """
    deadline = _deadline_s()
    if deadline <= 0:
        return await _investigate_loop(alert, index, window_minutes, max_steps, progress, reasoning)
    try:
        return await asyncio.wait_for(
            _investigate_loop(alert, index, window_minutes, max_steps, progress, reasoning),
            timeout=deadline,
        )
    except (asyncio.TimeoutError, TimeoutError):
        logger.warning(
            "agentic investigation exceeded %.2fs deadline; degrading", deadline
        )
        return _timeout_result()


async def _investigate_loop(
    alert: dict[str, Any],
    index: str,
    window_minutes: int,
    max_steps: int | None,
    progress: ProgressCb = None,
    reasoning: str | None = None,
) -> dict[str, Any]:
    steps_budget = max_steps if max_steps is not None else _max_steps()
    size_cap = _size_cap()
    token_budget = _token_budget()
    alert_src = _unwrap(alert)
    masked_alert = mask_doc(alert_src)
    wl = index_whitelist.get()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": agentic_investigate_system_prompt()},
        {
            "role": "user",
            # 时间窗按告警自己的时间算，不是按 now —— 见 build_agentic_investigate_prompt。
            "content": build_agentic_investigate_prompt(
                masked_alert, index, window_minutes, wl.patterns(),
                _time_bounds(alert_src, window_minutes),
            ),
        },
    ]
    await emit_stage(progress, "enrich", "资产/身份富化", "active")
    block = await asset_context_block(alert_src)
    await emit_stage(progress, "enrich", "资产/身份富化", "done")
    if block:
        messages[1]["content"] = f"资产语境:\n{block}\n\n{messages[1]['content']}"
    await emit_stage(progress, "retrieve", "检索证据", "active")
    router = get_router()
    trace: list[dict[str, Any]] = []
    hits_seen = 0
    tokens_used = 0
    budget_hit = False

    # Seed the loop with REAL-value context (masked before the model sees it), the
    # same subject+time-window pull the non-agentic path runs. Without this the
    # model only has the alert's MASKED entity values and builds es_search filters
    # from them → 0 hits in cloud/private masking (airgapped is a no-op, immune).
    # Starting from actual masked hits means the loop reasons over evidence instead
    # of blind-querying. See memory: agentic-masking-query-limitation.
    try:
        seed = await _gather_context(alert_src, index, window_minutes)
    except Exception as e:  # noqa: BLE001 — seeding is best-effort
        logger.debug("agentic seed context failed (%s); starting cold", e)
        seed = []
    unmask: dict[str, set[str]] = {}  # masked IP → real IPs seen in evidence (server-side only)
    if seed:
        _learn_ips(seed, unmask)
        masked_seed = [
            {"_id": h.get("_id"), "_source": mask_doc(h.get("_source", {}))} for h in seed
        ]
        hits_seen += len(masked_seed)
        seed_json = json.dumps(
            {"hits": masked_seed, "hit_count": len(masked_seed)}, ensure_ascii=False
        )
        messages[1]["content"] += (
            f"\n\n初始证据（已按主体+时间窗预取真实命中，共 {len(masked_seed)} 条，"
            f"实体值已脱敏）：\n{seed_json}\n"
            "以上是围绕本告警主体在时间窗内的真实日志。若已足够可直接给出结论；"
            "如需补充再调用 es_search。注意：文档里的实体值（IP/主机名/账号等）是脱敏占位；"
            "证据里出现过的 IP 可原样写进 term/terms 过滤（如 source.ip='10.10.x.x'，服务端会还原成真实值），"
            "其它脱敏值不能当过滤值，否则查不到数据。"
        )
        await emit_stage(
            progress, "retrieve", "检索证据", "active", f"预取初始证据 {len(masked_seed)} 条"
        )

    for step in range(steps_budget):
        try:
            resp, _p = await router.chat_completion(
                messages=messages,
                tools=[_core()["ES_SEARCH_TOOL"]],
                tool_choice="auto",
                temperature=0,
                # agentic 调查回合：选下一步查什么，不用长链推理；用户开关可覆盖
                reasoning=llm_reasoning.from_request(reasoning, "low"),
            )
        except Exception as e:  # noqa: BLE001
            if step == 0:
                # Provider likely can't do function-calling (or is down before we
                # made any progress). Fall back to the single-step path rather
                # than 500 — a non-tool model still gets to investigate.
                logger.warning(
                    "agentic first call failed (%s); falling back to single-step "
                    "investigate", e,
                )
                return await investigate_alert(
                    alert, index, window_minutes=window_minutes, progress=progress
                )
            # Mid-loop failure — finalize with whatever context we gathered.
            logger.warning(
                "agentic mid-loop call failed (%s); degrading with partial context", e
            )
            return _finalize("", hits_seen, trace)

        tokens_used += _usage_tokens(resp)
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            await emit_stage(progress, "retrieve", "检索证据", "done", f"共 {len(trace)} 轮")
            await emit_stage(progress, "analyze", "AI 分析中", "active")
            return _finalize(getattr(msg, "content", "") or "", hits_seen, trace)

        messages.append(_assistant_msg(msg))
        for tc in tool_calls:
            out, n = await _run_tool(tc, wl, size_cap, unmask)
            hits_seen += n
            trace.append({
                "tool": _tc_name(tc),
                "args": _tc_args_raw(tc)[:2000],
                "hit_count": n,
                "error": out.get("error"),
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(out, ensure_ascii=False),
            })
        await emit_stage(
            progress, "retrieve", "检索证据", "active",
            f"第 {step + 1} 轮 · 累计命中 {hits_seen} 条",
        )

        if token_budget and tokens_used >= token_budget:
            logger.info(
                "agentic token budget reached (%d/%d) after %d steps; forcing final",
                tokens_used, token_budget, step + 1,
            )
            budget_hit = True
            break

    # Step budget exhausted (or token budget hit) — force a tool-less final.
    await emit_stage(progress, "retrieve", "检索证据", "done", f"共 {len(trace)} 轮")
    await emit_stage(progress, "analyze", "AI 分析中", "active")
    reason = "token 预算已达上限" if budget_hit else "检索步数已达上限"
    messages.append({
        "role": "user",
        "content": f"{reason}。不要再调用工具,现在仅输出最终 JSON 调查结论。",
    })
    try:
        resp, _p = await router.chat_completion(
            messages=messages,
            tools=[_core()["ES_SEARCH_TOOL"]],
            tool_choice="none",
            temperature=0,
            reasoning=llm_reasoning.from_request(reasoning, "high"),  # agentic 收尾
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("agentic forced-final call failed (%s); degrading", e)
        return _finalize("", hits_seen, trace)
    msg = resp.choices[0].message
    return _finalize(getattr(msg, "content", "") or "", hits_seen, trace)
