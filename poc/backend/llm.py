import asyncio
import json
import logging
import os
import re
from typing import Any

from openai import AsyncOpenAI

from .api_errors import error_payload
from . import llm_reasoning
from .llm_router import get_router
from .prompts import system_prompt, build_user_prompt
from .rag import augment_prompt_meta

_VALID_CONFIDENCE = {"low", "medium", "high"}

logger = logging.getLogger("rst.llm")


def nl2dsl_reasoning() -> str | None:
    """NL→DSL 这一步要多少推理。默认 low：输出格式是死的（一段 JSON DSL），
    要的是「看清字段、别猜值」，不是长链推理。2026-09-14 实测 ark-code-latest
    开思考首字 30s、个别 300s 不出字。`native` = 不传参数，按模型默认。"""
    v = os.environ.get("RST_NL2DSL_REASONING", "").strip().lower() or "low"
    if v in ("none", "low", "high"):
        return v
    return None


def first_token_timeout_s() -> float:
    """流式生成里「第一个正文字符」的硬上限。思考模型可以想很久；超过这个数
    就中止并告诉用户换个问法 / 重试，而不是转圈到网关超时。0 = 不限。"""
    try:
        v = float(os.environ.get("RST_LLM_FIRST_TOKEN_TIMEOUT_S", "45") or "45")
    except ValueError:
        return 45.0
    return v if v > 0 else 0.0


def _reasoning_delta(chunk: Any) -> str | None:
    """供应商吐的推理增量（豆包 / DeepSeek / Qwen 都放在 delta.reasoning_content）。
    没有就 None。"""
    try:
        d = chunk.choices[0].delta
    except (AttributeError, IndexError):
        return None
    for name in ("reasoning_content", "reasoning"):
        v = getattr(d, name, None)
        if isinstance(v, str) and v:
            return v
    return None


def _get_client() -> AsyncOpenAI:
    """Backward-compat shim — returns the FIRST enabled provider's client.

    Kept so legacy code that imported `_get_client` keeps working. New code
    should use `get_router().chat_completion(...)` for failover support.
    """
    router = get_router()
    enabled = next((p for p in router.providers if p.enabled), None)
    if not enabled:
        raise RuntimeError(
            "No enabled LLM provider. Configure llm_providers.yml or set "
            "LLM_API_KEY / LLM_MODEL / LLM_BASE_URL."
        )
    return router._get_client(enabled)


def parse_time_intent(payload: dict[str, Any]) -> dict[str, Any] | None:
    """从模型输出里取出 `time_intent`，形状不对就当没有。

    它决定「问题里的时间」和「界面上的筛选器」谁说了算，所以宁可判成没有（退回
    筛选器优先，也就是加这个字段之前的行为），也不要把一个半截的对象往下传。
    """
    raw = payload.get("time_intent")
    if not isinstance(raw, dict) or not raw.get("explicit"):
        return None
    out: dict[str, Any] = {"explicit": True}
    for key in ("text", "since", "until"):
        v = raw.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    # 没有 since 就没法同步筛选器，也没法说清「按问题里的时间」是哪一段 —— 这种
    # 半截的声明不如不要。
    return out if "since" in out else None


async def generate_dsl(
    question: str,
    index: str,
    mapping: dict[str, Any],
    prior_turns: list[dict[str, Any]] | None = None,
    field_samples: dict[str, list[str]] | None = None,
    examples: list[dict[str, Any]] | None = None,
    reasoning: str | None = None,
) -> tuple[dict | None, str, str, str | None, dict[str, Any] | None]:
    """Returns (dsl_or_none, explanation, confidence, confidence_reason, time_intent).

    Calls the LLM router which tries each enabled provider in order
    (failover) until one succeeds.
    """
    router = get_router()
    user_prompt = build_user_prompt(
        question, index, mapping, prior_turns=prior_turns, field_samples=field_samples,
        examples=examples,
    )
    # Customer KB (field meanings, business conventions). Best-effort: no embed
    # model / empty KB / ES error all leave the prompt untouched.
    user_prompt, rag_used = await augment_prompt_meta(
        user_prompt, top_k=3, retrieval_query=question
    )
    if rag_used:
        logger.info("generate_dsl_rag", extra={"chunks_used": rag_used})
    messages = [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": user_prompt},
    ]
    resp, provider = await router.chat_completion(
        messages=messages, temperature=0, reasoning=llm_reasoning.from_request(reasoning, nl2dsl_reasoning()),
    )
    if not resp.choices:
        raise ValueError("模型未返回内容,请重试。")
    raw = resp.choices[0].message.content or ""
    payload = await parse_or_retry(raw, messages)

    if "dsl" not in payload:
        raise ValueError(f"LLM output missing 'dsl' key. Raw: {raw[:500]}")
    dsl = payload["dsl"]
    if dsl is not None and not isinstance(dsl, dict):
        raise ValueError(f"LLM output 'dsl' must be dict or null. Raw: {raw[:500]}")
    if dsl is not None:
        dsl = await repair_invalid_query(index, messages, normalize_dsl(dsl))

    confidence = payload.get("confidence", "medium")
    if not isinstance(confidence, str) or confidence not in _VALID_CONFIDENCE:
        confidence = "medium"

    confidence_reason = payload.get("confidence_reason")
    if confidence_reason is not None and not isinstance(confidence_reason, str):
        confidence_reason = None

    return (dsl, payload.get("explanation", ""), confidence, confidence_reason,
            parse_time_intent(payload))


async def generate_dsl_stream(
    question: str,
    index: str,
    mapping: dict[str, Any],
    prior_turns: list[dict[str, Any]] | None = None,
    field_samples: dict[str, list[str]] | None = None,
    examples: list[dict[str, Any]] | None = None,
    reasoning: str | None = None,
):
    """Streaming version of generate_dsl. Yields a series of dicts:

      {type: "thinking", text: <delta>}          模型的推理增量（有就转发）
      {type: "chunk", text: <delta>, provider: <id>}
      {type: "done", dsl, explanation, confidence, confidence_reason, time_intent, raw}
      {type: "error", message: <str>, code?: <str>}

    第一个正文字符有硬上限（first_token_timeout_s）：思考模型想过头时中止，
    error 带 code=llm_first_token_timeout，界面据此给「换个问法 / 重试」。
    The caller is responsible for serializing these to SSE frames.
    """
    router = get_router()
    user_prompt = build_user_prompt(
        question, index, mapping, prior_turns=prior_turns, field_samples=field_samples,
        examples=examples,
    )
    user_prompt, rag_used = await augment_prompt_meta(
        user_prompt, top_k=3, retrieval_query=question
    )
    if rag_used:
        logger.info("generate_dsl_rag", extra={"chunks_used": rag_used})
    messages = [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": user_prompt},
    ]

    accumulated: list[str] = []
    provider_id: str | None = None
    usage_obj: Any = None
    thinking_chars = 0

    agen = router.chat_completion_stream(
        messages=messages, temperature=0, reasoning=llm_reasoning.from_request(reasoning, nl2dsl_reasoning()),
    )
    limit = first_token_timeout_s()
    deadline = asyncio.get_running_loop().time() + limit if limit else None
    try:
        while True:
            # 正文没出来之前每一步都套 deadline；出来了就不管了——写正文的速度
            # 不是这里要防的。
            if deadline is not None and not accumulated:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                try:
                    provider, chunk = await asyncio.wait_for(agen.__anext__(), remaining)
                except StopAsyncIteration:
                    break
            else:
                try:
                    provider, chunk = await agen.__anext__()
                except StopAsyncIteration:
                    break
            provider_id = provider.id
            # The final usage-only chunk (empty choices) carries token counts.
            u = getattr(chunk, "usage", None)
            if u is not None:
                usage_obj = u
            think = _reasoning_delta(chunk)
            if think:
                thinking_chars += len(think)
                yield {"type": "thinking", "text": think}
            try:
                delta = chunk.choices[0].delta.content
            except (AttributeError, IndexError):
                delta = None
            if not delta:
                continue
            accumulated.append(delta)
            yield {"type": "chunk", "text": delta, "provider": provider_id}
    except asyncio.TimeoutError:
        await agen.aclose()
        logger.warning(
            "generate_dsl_first_token_timeout",
            extra={"limit_s": limit, "thinking_chars": thinking_chars, "provider": provider_id},
        )
        body = error_payload("llm_first_token_timeout", limit_s=int(limit))
        yield {"type": "error", "message": body["detail"], "code": body["code"], "params": body["params"]}
        return
    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "message": f"LLM streaming failed: {e}"}
        return

    raw = "".join(accumulated)
    try:
        # The retry is a plain (non-streamed) call: the text on screen is already
        # final, and the `done` frame below is what the UI actually consumes.
        payload = await parse_or_retry(raw, messages)
    except ValueError as e:
        yield {"type": "error", "message": f"LLM output is not parseable JSON: {e}"}
        return

    if "dsl" not in payload:
        yield {"type": "error", "message": f"LLM output missing 'dsl' key. Raw: {raw[:500]}"}
        return
    dsl = payload["dsl"]
    if dsl is not None and not isinstance(dsl, dict):
        yield {"type": "error", "message": f"LLM output 'dsl' must be dict or null. Raw: {raw[:500]}"}
        return
    if dsl is not None:
        # The streamed text is already on screen; the `done` frame below carries
        # the authoritative DSL, so a repair here still reaches the operator.
        dsl = await repair_invalid_query(index, messages, normalize_dsl(dsl))

    confidence = payload.get("confidence", "medium")
    if not isinstance(confidence, str) or confidence not in _VALID_CONFIDENCE:
        confidence = "medium"
    confidence_reason = payload.get("confidence_reason")
    if confidence_reason is not None and not isinstance(confidence_reason, str):
        confidence_reason = None

    yield {
        "type": "done",
        "dsl": dsl,
        "explanation": payload.get("explanation", ""),
        "confidence": confidence,
        "confidence_reason": confidence_reason,
        "time_intent": parse_time_intent(payload),
        "provider": provider_id,
        "rag_used": rag_used,
        "raw_chars": len(raw),
        "output_chars": len(raw),
        "thinking_chars": thinking_chars,
        "usage": _usage_dict(usage_obj),
    }


def _usage_dict(u: Any) -> dict | None:
    """Normalize an OpenAI usage object to a plain dict, or None if absent."""
    if u is None:
        return None
    try:
        return {
            "prompt_tokens": getattr(u, "prompt_tokens", None),
            "completion_tokens": getattr(u, "completion_tokens", None),
            "total_tokens": getattr(u, "total_tokens", None),
        }
    except Exception:  # noqa: BLE001
        return None


def _normalize_punct(s: str) -> str:
    """Full-width punctuation LLMs slip into JSON structure."""
    return (
        s
        .replace("，", ",")
        .replace("：", ":")
        .replace("；", ";")
        .replace("“", '"').replace("”", '"')
        .replace("‘", "'").replace("’", "'")
    )


def _balance(text: str) -> str:
    """Close whatever the model left open — an unterminated string, then any
    still-open `[` / `{` in reverse order. Only ever appends.

    The single most common defect in the eval corpus: the model omits the brace
    that closes `dsl`, so the output ends one `}` short and json.loads reports
    "Expecting ',' delimiter" at exactly the last character. 51 of 72 eval
    failures were this; balancing recovers 46 of them.
    """
    stack: list[str] = []
    in_str = False
    esc = False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack and stack[-1] == ("{" if ch == "}" else "["):
                stack.pop()
    out = text
    if in_str:
        out += '"'
    for ch in reversed(stack):
        out += "}" if ch == "{" else "]"
    return out


def parse_json(text: str) -> dict:
    raw = text
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # 1) strict
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2) slice to first {...}
    start = text.find("{")
    end = text.rfind("}")
    candidate = text[start : end + 1] if start >= 0 and end > start else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # 3) normalize common full-width punctuation that LLMs slip in
    normalized = _normalize_punct(candidate)
    try:
        return json.loads(normalized)
    except json.JSONDecodeError:
        pass

    # 4) close what the model left open. Balance `text`, not `candidate` — the
    #    slice in step 2 cuts at the LAST `}`, which throws away the tail when
    #    the missing brace is the outermost one.
    for repaired in (_balance(text), _balance(_normalize_punct(text))):
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as e:
            last = e

    # 5) a Python dict repr ({'k': 'v', 'flag': False}) — ark-code-latest did
    #    this on a long investigation verdict (2026-09-19). Literals only, so
    #    literal_eval is safe; anything that isn't a dict is still an error.
    try:
        import ast
        obj = ast.literal_eval(candidate)
        if isinstance(obj, dict):
            return obj
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        pass
    raise ValueError(
        f"Cannot parse LLM output as JSON ({last}). "
        f"Raw output (first 1500 chars):\n{raw[:1500]}"
    )


_CONTRACT_KEYS = ("explanation", "confidence", "confidence_reason")
_CALENDAR_UNITS = {"w", "M", "q", "y", "week", "month", "quarter", "year"}
_INTERVAL_RE = re.compile(
    r"(\d*)\s*(ms|s|m|h|d|w|M|q|y|second|minute|hour|day|week|month|quarter|year)"
)


def lift_contract_keys(payload: dict, container: str) -> dict:
    """Move explanation/confidence back out of `dsl` (or `rule`) to the top level.

    The model drops the brace that closes the container far more often than it
    drops the outermost one, so the sibling contract keys end up *inside* it —
    which ES then rejects with "Unknown key for a VALUE_STRING in [explanation]".
    Only string values are lifted, so a legitimately nested query clause of the
    same name is left alone.
    """
    inner = payload.get(container)
    if not isinstance(inner, dict):
        return payload
    for key in _CONTRACT_KEYS:
        if isinstance(inner.get(key), str):
            payload.setdefault(key, inner.pop(key))
    # time_intent is the one dict-valued contract key; models put it inside
    # `dsl` too, and ES answers "Unknown key for a START_OBJECT in [time_intent]".
    if isinstance(inner.get("time_intent"), dict) and "explicit" in inner["time_intent"]:
        payload.setdefault("time_intent", inner.pop("time_intent"))
    if not inner:
        # Nothing left but prose — that is a refusal, not an empty match-all query.
        payload[container] = None
    return payload


def normalize_dsl(dsl: Any) -> Any:
    """Rename `date_histogram.interval`, removed in ES 8, to its replacement.

    Models trained on 7.x docs keep emitting it. `interval` maps to
    calendar_interval for a single calendar unit and fixed_interval otherwise;
    a multiple of a calendar unit ("2w") is legal under neither, so it is left
    untouched rather than silently given a different meaning.
    """
    if isinstance(dsl, list):
        return [normalize_dsl(v) for v in dsl]
    if not isinstance(dsl, dict):
        return dsl
    for key, value in list(dsl.items()):
        if (
            key == "date_histogram"
            and isinstance(value, dict)
            and isinstance(value.get("interval"), str)
            and "fixed_interval" not in value
            and "calendar_interval" not in value
        ):
            m = _INTERVAL_RE.fullmatch(value["interval"].strip())
            if m:
                qty, unit = m.group(1), m.group(2)
                calendar = unit in _CALENDAR_UNITS
                if not qty:
                    value["calendar_interval"] = value.pop("interval")
                elif not calendar:
                    value["fixed_interval"] = value.pop("interval")
                elif qty == "1":
                    value["calendar_interval"] = value.pop("interval")
        dsl[key] = normalize_dsl(value)
    return dsl


# ── One corrective round-trip ───────────────────────────────────────────────


def _correction_timeout() -> float:
    """Wall-clock budget for a corrective round-trip, in seconds.

    A provider's own timeout (llm_providers.yml `timeout_s`, default 180s)
    applies per call, so a correction inheriting it would double the worst-case
    wait on /api/generate. A correction re-asks a question the model has already
    answered once — it should come back fast or not at all.
    """
    try:
        v = float(os.environ.get("RST_LLM_CORRECTION_TIMEOUT_S", "").strip())
    except ValueError:
        return 45.0
    return v if v > 0 else 45.0


async def _correct(
    messages: list[dict[str, Any]], instruction: str, prior_output: str
) -> dict | None:
    """Re-ask the model once, showing it what it produced and what was wrong.

    Returns the parsed payload, or None if anything at all goes wrong — every
    caller keeps whatever it already had, so a correction can never turn a
    working response into a failed one.
    """
    try:
        resp, _ = await get_router().chat_completion(
            messages=[
                *messages,
                # Without its own output in the context the model corrects blind
                # and tends to reproduce the same mistake.
                {"role": "assistant", "content": prior_output[:8000]},
                {"role": "user", "content": instruction},
            ],
            temperature=0,
            reasoning="low",  # 纠错重问：输出格式已定，只要它照着改
            timeout=_correction_timeout(),
        )
        raw = resp.choices[0].message.content or "" if resp.choices else ""
        return lift_contract_keys(parse_json(raw), "dsl")
    except Exception as e:  # noqa: BLE001
        logger.warning("llm correction round-trip failed", extra={"error": str(e)[:200]})
        return None


_REPARSE_PROMPT = """上一次输出不是合法 JSON，无法解析。

报错：{error}

请重新输出**完整**的 JSON，沿用同样的输出契约：只有一个顶层对象，顶层键为
dsl / explanation / confidence / confidence_reason。不要用 ``` 包裹，不要输出 JSON 以外的
任何文字，并确认每一个 {{、[、" 都已闭合。"""


async def parse_or_retry(raw: str, messages: list[dict[str, Any]]) -> dict:
    """Parse the model's output, re-asking once if it is beyond repair.

    `parse_json` recovers the common truncations; what reaches the retry is
    output no amount of appending fixes. The original parse error is raised when
    the retry doesn't help, so the operator still sees the first failure rather
    than a second, less representative one.
    """
    try:
        return lift_contract_keys(parse_json(raw), "dsl")
    except ValueError as first:
        payload = await _correct(messages, _REPARSE_PROMPT.format(error=str(first)[:400]), raw)
        if payload is None:
            raise first
        logger.info("llm output reparsed after retry")
        return payload


# ── ES pre-flight ───────────────────────────────────────────────────────────
#
# Generation and execution are separate requests by design — the operator reviews
# the DSL before it runs — so nothing downstream can feed an ES error back to the
# model. `_validate/query` closes that loop without executing anything: it parses
# the query clause, which is where the date math the model keeps inventing
# ("now/M-1ms" — ES has no `ms` unit) fails.
#
# Aggregations have no dry-run in ES, so they get a *near-free* real run instead:
# the same DSL with size=0 and terminate_after=1. Agg-shaped mistakes (fielddata on
# _id, ordering by a path that is not `_count`, "1day" as a calendar_interval)
# are raised while the request is being set up, before a single document is
# scored, so one document is all it ever touches. 2026-09-14: with reasoning off
# for NL→DSL these three were 3 of 30 eval cases; the pre-flight + one repair
# round gets them back without paying 30 s of thinking per question.

_REPAIR_PROMPT = """上一次生成的 DSL 无法通过 Elasticsearch 校验。

报错：{error}

请修正后重新输出**完整**的 JSON（沿用同样的输出契约）。ES 日期数学的三条硬规则：
1. 单位只有 y、M、w、d、h/H、m、s —— **没有 ms**。"上个月最后一刻"写 `now/M-1s`，不是 `now/M-1ms`
2. 表达式里**不能有空格**：`now-1w/w + 5d/d` 会被拒，写成 `now-1w/w+5d/d`
3. 一次加减只带**一个**单位：`now+23h59m59s` 会被拒；要多个就分开写，`now+23h+59m+59s`
取整 `/单位` 放在运算前后都合法（`now/M-1d`、`now-1d/d` 都可以）。
聚合的三条硬规则：
4. `date_histogram` 的 `calendar_interval` 只认 `minute/hour/day/week/month/quarter/year`
   或 `1m/1h/1d/1w/1M/1q/1y`（**没有 `1day`**）；要 5 分钟这种非 1 的倍数用 `fixed_interval`
5. 按数量排序写 `"order": {{"_count": "desc"}}`，**不是** `doc_count`；按子聚合排序用子聚合的名字
6. `_id` 不能做 terms / cardinality 的 field —— 数文档用 `value_count` 配任何 keyword 字段，或直接看 hits.total
真的表达不了就换成近似时间窗，并在 explanation 注明是近似。"""


async def _query_parse_error(index: str, dsl: dict) -> str | None:
    """ES's own verdict on whether the query clause parses. None = fine.

    Any failure to reach ES also returns None: a probe outage must never block
    generation — the worst case is the pre-existing behaviour.
    """
    query = dsl.get("query")
    if not isinstance(query, dict):
        return None
    try:
        from .es_client import get_es
        body = (await get_es().indices.validate_query(
            index=index, query=query, explain=True
        )).body
    except Exception:  # noqa: BLE001
        return None
    if body.get("valid"):
        return None
    explanations = body.get("explanations") or []
    error = explanations[0].get("error") if explanations else None
    return error or "query is not valid"


def _es_error_text(e: Exception) -> str:
    """把 elasticsearch-py 的异常压成一句能喂回模型的话（reason 优先）。"""
    info = getattr(e, "body", None)
    if not isinstance(info, dict):
        info = getattr(e, "info", None)
    if isinstance(info, dict):
        err = info.get("error")
        if isinstance(err, dict):
            root = (err.get("root_cause") or [{}])[0]
            reason = root.get("reason") or err.get("reason")
            if reason:
                return str(reason)
    return str(e)


async def _agg_preflight_error(index: str, dsl: dict) -> str | None:
    """聚合的近零成本试跑：size=0 + terminate_after=1。None = 能跑。

    只对带聚合的 DSL 做；ES 够不着或超时同样返回 None——探针挂了不能挡生成。
    只把 4xx 当「DSL 有问题」：5xx / 超时是集群的事，不是模型的事。
    """
    if not isinstance(dsl.get("aggs") or dsl.get("aggregations"), dict):
        return None
    probe = {k: v for k, v in dsl.items() if k not in ("size", "from", "sort", "_source", "terminate_after")}
    probe["size"] = 0
    probe["terminate_after"] = 1
    try:
        from .es_client import get_es
        await get_es().search(index=index, body=probe, request_timeout=8)
    except Exception as e:  # noqa: BLE001
        status = getattr(e, "status_code", None) or getattr(e, "status", None)
        if isinstance(status, int) and 400 <= status < 500:
            return _es_error_text(e)
        return None
    return None


async def repair_invalid_query(
    index: str, messages: list[dict[str, Any]], dsl: dict
) -> dict:
    """One corrective LLM round-trip when ES says the DSL won't run.

    Two probes, both cheap: `_validate/query` for the query clause, a
    size=0/terminate_after=1 search for the aggregations. Returns the repaired
    DSL, or the original when there is nothing to fix, the retry fails, or the
    retry comes back just as broken.
    """
    error = await _query_parse_error(index, dsl)
    if error is None:
        error = await _agg_preflight_error(index, dsl)
    if error is None:
        return dsl
    payload = await _correct(
        messages,
        _REPAIR_PROMPT.format(error=error[:400]),
        json.dumps({"dsl": dsl}, ensure_ascii=False),
    )
    if payload is None:
        return dsl
    candidate = payload.get("dsl")
    if not isinstance(candidate, dict):
        return dsl
    candidate = normalize_dsl(candidate)
    if await _query_parse_error(index, candidate) is not None:
        return dsl
    if await _agg_preflight_error(index, candidate) is not None:
        return dsl
    logger.info("dsl repaired after ES validation error", extra={"es_error": error[:200]})
    return candidate
