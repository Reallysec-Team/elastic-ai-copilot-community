"""Recovery of the malformed DSL the model actually emits.

Every literal below is a real (abbreviated) eval failure. Across 30 eval runs,
72 cases failed; 57 of them were one slip — the brace closing `dsl` goes missing,
so `explanation` / `confidence` are swallowed into the query body.
"""
import json

import pytest

from backend.llm import (
    _balance,
    _correction_timeout,
    parse_json,
    _query_parse_error,
    lift_contract_keys,
    normalize_dsl,
    parse_or_retry,
    repair_invalid_query,
)


class _FakeRouter:
    """Router stub that returns one canned completion and records the call."""

    def __init__(self, content: str):
        self._content = content
        self.calls: list[dict] = []

    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        choice = type("C", (), {"message": type("M", (), {"content": self._content})})
        return type("R", (), {"choices": [choice]}), None


# ── the missing brace ────────────────────────────────────────────────────────

def test_parses_output_missing_the_brace_that_closes_dsl():
    raw = ('{"dsl":{"size":0,"query":{"range":{"@timestamp":{"gte":"now/d"}}}},'
           '"explanation":"统计今天的请求数。","confidence":"high"')
    assert parse_json(raw)["explanation"] == "统计今天的请求数。"


def test_lifts_contract_keys_swallowed_into_dsl():
    payload = {"dsl": {"size": 0, "explanation": "统计今天。", "confidence": "high"}}
    lifted = lift_contract_keys(payload, "dsl")
    assert lifted["dsl"] == {"size": 0}
    assert lifted["explanation"] == "统计今天。"
    assert lifted["confidence"] == "high"


def test_end_to_end_recovery_of_a_real_failure():
    """The exact shape of 51 of the 72 eval failures."""
    raw = ('{"dsl":{"size":20,"query":{"bool":{"filter":[{"range":{"response":'
           '{"gte":"500"}}}]}},"explanation":"查询 5xx 错误日志。","confidence":"high"}')
    payload = lift_contract_keys(parse_json(raw), "dsl")
    assert "explanation" not in payload["dsl"]
    assert payload["dsl"]["size"] == 20
    assert payload["explanation"] == "查询 5xx 错误日志。"


def test_prose_only_container_becomes_a_refusal():
    payload = lift_contract_keys({"dsl": {"explanation": "做不到。"}}, "dsl")
    assert payload["dsl"] is None
    assert payload["explanation"] == "做不到。"


def test_a_non_string_field_of_the_same_name_is_left_alone():
    """A nested `explanation` that isn't the contract key must not be hoisted."""
    payload = lift_contract_keys({"dsl": {"explanation": {"nested": 1}}}, "dsl")
    assert payload["dsl"] == {"explanation": {"nested": 1}}
    assert "explanation" not in payload


def test_balance_only_appends():
    assert _balance('{"a":1').startswith('{"a":1')
    assert _balance('{"a":"unterminated') == '{"a":"unterminated"}'
    assert _balance('{"a":[1,2') == '{"a":[1,2]}'
    assert _balance('{"a":"}"}') == '{"a":"}"}'  # brace inside a string


def test_valid_json_is_untouched():
    assert parse_json('{"dsl":{"size":1},"explanation":"x"}') == {
        "dsl": {"size": 1}, "explanation": "x"
    }


def test_unrecoverable_output_still_raises():
    with pytest.raises(ValueError, match="Cannot parse LLM output"):
        parse_json("这不是 JSON")


# ── date_histogram.interval, removed in ES 8 ─────────────────────────────────

@pytest.mark.parametrize("given,key,value", [
    ("hour", "calendar_interval", "hour"),     # the real eval failure
    ("day", "calendar_interval", "day"),
    ("1w", "calendar_interval", "1w"),
    ("1h", "fixed_interval", "1h"),
    ("30m", "fixed_interval", "30m"),
    ("7d", "fixed_interval", "7d"),
])
def test_interval_is_renamed_to_the_form_es8_accepts(given, key, value):
    dsl = normalize_dsl({"aggs": {"h": {"date_histogram": {"field": "@timestamp", "interval": given}}}})
    agg = dsl["aggs"]["h"]["date_histogram"]
    assert "interval" not in agg
    assert agg[key] == value


def test_multiple_of_a_calendar_unit_is_left_alone():
    """`2w` is legal under neither replacement — guessing would change meaning."""
    dsl = normalize_dsl({"aggs": {"h": {"date_histogram": {"interval": "2w"}}}})
    assert dsl["aggs"]["h"]["date_histogram"] == {"interval": "2w"}


def test_explicit_interval_key_is_not_overwritten():
    agg = {"date_histogram": {"fixed_interval": "1h", "interval": "hour"}}
    assert normalize_dsl(agg)["date_histogram"]["interval"] == "hour"


# ── ES pre-flight ────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_preflight_is_silent_when_es_is_unreachable(monkeypatch):
    """A probe outage must never block generation."""
    import backend.es_client as es_client

    def boom():
        raise RuntimeError("ES down")

    monkeypatch.setattr(es_client, "get_es", boom)
    assert await _query_parse_error("idx", {"query": {"match_all": {}}}) is None


@pytest.mark.anyio
async def test_repair_returns_original_when_query_is_valid(monkeypatch):
    async def valid(index, dsl):
        return None

    monkeypatch.setattr("backend.llm._query_parse_error", valid)
    dsl = {"query": {"match_all": {}}}
    assert await repair_invalid_query("idx", [], dsl) is dsl


@pytest.mark.anyio
async def test_repair_shows_the_model_its_own_dsl(monkeypatch):
    """Correcting blind reproduces the same mistake — the bad DSL must be in context."""
    async def once_bad(index, dsl):
        return None if "gte" in str(dsl) else "operator not supported [/M-1ms]"

    router = _FakeRouter('{"dsl":{"query":{"range":{"@timestamp":{"gte":"now-30d"}}}},'
                         '"explanation":"近 30 天（近似）。"}')
    monkeypatch.setattr("backend.llm._query_parse_error", once_bad)
    monkeypatch.setattr("backend.llm.get_router", lambda: router)

    fixed = await repair_invalid_query("idx", [], {"query": {"range": {"@timestamp": {"lt": "now/M-1ms"}}}})
    assert fixed == {"query": {"range": {"@timestamp": {"gte": "now-30d"}}}}
    sent = router.calls[0]["messages"]
    assert sent[-2]["role"] == "assistant" and "now/M-1ms" in sent[-2]["content"]
    assert "M-1ms" in sent[-1]["content"]  # ES's own error reaches the model


@pytest.mark.anyio
async def test_repair_keeps_the_original_when_the_retry_is_also_broken(monkeypatch):
    async def always_bad(index, dsl):
        return "operator not supported for date math [/M-1ms]"

    async def blow_up(**kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr("backend.llm._query_parse_error", always_bad)
    monkeypatch.setattr("backend.llm.get_router", lambda: type(
        "R", (), {"chat_completion": staticmethod(blow_up)})())
    dsl = {"query": {"range": {"@timestamp": {"lt": "now/M-1ms"}}}}
    assert await repair_invalid_query("idx", [], dsl) is dsl


# ── retry on unparseable output ──────────────────────────────────────────────

@pytest.mark.anyio
async def test_parse_needs_no_retry_when_the_output_is_recoverable(monkeypatch):
    """The cheap path stays cheap — a missing brace must not cost a second call."""
    router = _FakeRouter("{}")
    monkeypatch.setattr("backend.llm.get_router", lambda: router)

    payload = await parse_or_retry('{"dsl":{"size":1},"explanation":"x"', [])
    assert payload["dsl"] == {"size": 1}
    assert router.calls == []


@pytest.mark.anyio
async def test_unparseable_output_is_regenerated_once(monkeypatch):
    router = _FakeRouter('{"dsl":{"size":1},"explanation":"重新生成。","confidence":"high"}')
    monkeypatch.setattr("backend.llm.get_router", lambda: router)

    payload = await parse_or_retry("模型这次只回了一段话，没有 JSON。", [])
    assert payload["dsl"] == {"size": 1}
    assert payload["explanation"] == "重新生成。"
    assert len(router.calls) == 1


@pytest.mark.anyio
async def test_retry_that_also_fails_raises_the_original_error(monkeypatch):
    """The first failure is the representative one — don't bury it."""
    monkeypatch.setattr("backend.llm.get_router", lambda: _FakeRouter("还是一段话。"))

    with pytest.raises(ValueError, match="这不是 JSON"):
        await parse_or_retry("这不是 JSON", [])


@pytest.mark.anyio
async def test_correction_carries_its_own_timeout(monkeypatch):
    """A correction must not inherit the provider's full 180s budget."""
    router = _FakeRouter('{"dsl":{"size":1},"explanation":"x"}')
    monkeypatch.setattr("backend.llm.get_router", lambda: router)

    await parse_or_retry("不是 JSON", [])
    assert router.calls[0]["timeout"] == 45.0


@pytest.mark.parametrize("raw,expected", [("", 45.0), ("90", 90.0), ("0", 45.0), ("x", 45.0)])
def test_correction_timeout_is_configurable(monkeypatch, raw, expected):
    monkeypatch.setenv("RST_LLM_CORRECTION_TIMEOUT_S", raw)
    assert _correction_timeout() == expected


def test_lift_contract_keys_moves_time_intent_out_of_dsl():
    # Cold-start 2026-09-12: ark-code-latest put time_intent inside dsl and the
    # gateway forwarded it verbatim → ES 400 on the product's own first example.
    ti = {"explicit": True, "text": "最近 24 小时", "since": "2026-09-10T15:44:00+00:00"}
    payload = {"dsl": {"size": 0, "query": {"match_all": {}}, "time_intent": dict(ti)}}
    lifted = lift_contract_keys(payload, "dsl")
    assert "time_intent" not in lifted["dsl"]
    assert lifted["time_intent"] == ti


def test_lift_contract_keys_leaves_a_real_time_intent_clause_alone():
    # A field literally named time_intent inside a query must not be touched.
    payload = {"dsl": {"query": {"term": {"time_intent": "x"}}}}
    assert lift_contract_keys(payload, "dsl")["dsl"] == {"query": {"term": {"time_intent": "x"}}}


# ── 聚合试跑（size=0 + terminate_after=1）────────────────────────────────────

class _Es400(Exception):
    status_code = 400

    def __init__(self, reason: str):
        super().__init__(reason)
        self.info = {"error": {"root_cause": [{"reason": reason}]}}


class _EsProbe:
    def __init__(self, fail_with: Exception | None = None):
        self.fail_with = fail_with
        self.bodies: list[dict] = []

    async def search(self, *, index, body, request_timeout=None):
        self.bodies.append(body)
        if self.fail_with:
            raise self.fail_with
        return type("R", (), {"body": {}})


@pytest.mark.asyncio
async def test_agg_preflight_skips_dsl_without_aggs(monkeypatch):
    from backend import es_client
    from backend.llm import _agg_preflight_error
    es = _EsProbe(fail_with=_Es400("should not be called"))
    monkeypatch.setattr(es_client, "get_es", lambda: es)
    assert await _agg_preflight_error("idx", {"query": {"match_all": {}}}) is None
    assert es.bodies == []


@pytest.mark.asyncio
async def test_agg_preflight_runs_size0_terminate1_and_surfaces_400(monkeypatch):
    from backend import es_client
    from backend.llm import _agg_preflight_error
    es = _EsProbe(fail_with=_Es400("Invalid aggregation order path [doc_count]"))
    monkeypatch.setattr(es_client, "get_es", lambda: es)
    dsl = {"size": 50, "sort": [{"@timestamp": "desc"}], "query": {"match_all": {}},
           "aggs": {"by_ip": {"terms": {"field": "ip", "order": {"doc_count": "desc"}}}}}
    err = await _agg_preflight_error("idx", dsl)
    assert err == "Invalid aggregation order path [doc_count]"
    probe = es.bodies[0]
    assert probe["size"] == 0 and probe["terminate_after"] == 1 and "sort" not in probe


@pytest.mark.asyncio
async def test_agg_preflight_ignores_cluster_side_failures(monkeypatch):
    from backend import es_client
    from backend.llm import _agg_preflight_error

    class _Es503(Exception):
        status_code = 503

    es = _EsProbe(fail_with=_Es503("no shards"))
    monkeypatch.setattr(es_client, "get_es", lambda: es)
    assert await _agg_preflight_error("idx", {"aggs": {"a": {"terms": {"field": "x"}}}}) is None


@pytest.mark.asyncio
async def test_repair_uses_agg_error_when_query_clause_is_fine(monkeypatch):
    fixed_dsl = {"aggs": {"by_ip": {"terms": {"field": "ip", "order": {"_count": "desc"}}}}}
    router = _FakeRouter(json.dumps({"dsl": fixed_dsl, "explanation": "x", "confidence": "high"}))
    monkeypatch.setattr("backend.llm.get_router", lambda: router)

    async def fine(_index, _dsl):
        return None
    monkeypatch.setattr("backend.llm._query_parse_error", fine)

    seen: list[dict] = []

    async def agg_probe(_index, dsl):
        seen.append(dsl)
        return "Invalid aggregation order path [doc_count]" if len(seen) == 1 else None
    monkeypatch.setattr("backend.llm._agg_preflight_error", agg_probe)

    broken = {"aggs": {"by_ip": {"terms": {"field": "ip", "order": {"doc_count": "desc"}}}}}
    out = await repair_invalid_query("idx", [], broken)
    assert out == fixed_dsl
    assert "doc_count" in router.calls[0]["messages"][-1]["content"]
