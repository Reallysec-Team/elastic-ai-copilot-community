"""The repair path against a real Elasticsearch — no LLM calls.

test_dsl_repair.py proves the logic with a stubbed ES. What it cannot prove is
that ES actually rejects the thing we built the pre-flight for: the date math
the model keeps inventing. If `_validate/query` quietly accepted `now/M-1ms`,
every unit test here would still pass and the feature would do nothing.

The LLM is still stubbed — the correction it would return is fixed, and paying
for a real one proves nothing extra. ES is not.

Skipped when no ES is reachable, so this stays runnable in CI without one.
"""
import json
import os
import urllib.error
import urllib.request

import pytest

from backend.llm import _query_parse_error, repair_invalid_query

ES_URL = os.environ.get("ES_URL", "http://localhost:9200").rstrip("/")
INDEX = "kibana_sample_data_logs"

# Date math ES refuses: `ms` is not one of its units (y M w d h/H m s). Real
# generations reached for this whenever a case said "上个月" — `now/M-1ms` as
# "the last instant of last month". Note it is the UNIT that is rejected, not the
# rounding order: `now/M-1s` and `now/M-1d` both validate fine.
BAD_DATE_MATH = {"query": {"range": {"@timestamp": {"lt": "now/M-1ms"}}}}
CORRECTED = {"query": {"range": {"@timestamp": {"gte": "now-30d"}}}}
STILL_BAD = {"query": {"range": {"@timestamp": {"lt": "now-1ms"}}}}


def _index_available() -> bool:
    try:
        with urllib.request.urlopen(f"{ES_URL}/{INDEX}", timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


pytestmark = pytest.mark.skipif(
    not _index_available(), reason=f"needs a live ES with {INDEX} at {ES_URL}"
)


@pytest.fixture(autouse=True)
async def _es_client_per_loop():
    """Rebuild the ES client for each test.

    `es_client._es` is a module global holding an aiohttp session bound to the
    event loop that created it, and anyio gives every test a fresh loop. Reusing
    it across tests makes the probe raise — which `_query_parse_error` swallows
    by design, so the repair silently no-ops and the test fails somewhere else
    entirely.
    """
    from backend import es_client

    async def _drop():
        try:
            await es_client.close_es()
        except Exception:  # noqa: BLE001 — a client bound to a dead loop
            es_client._es = None

    await _drop()
    yield
    await _drop()


class _FixedRouter:
    """Stands in for the model: always answers with the corrected DSL."""

    def __init__(self):
        self.calls: list[dict] = []

    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        content = json.dumps({"dsl": CORRECTED, "explanation": "近 30 天（近似）。",
                              "confidence": "medium"}, ensure_ascii=False)
        choice = type("C", (), {"message": type("M", (), {"content": content})})
        return type("R", (), {"choices": [choice]}), None


@pytest.mark.anyio
async def test_es_really_rejects_the_date_math_the_model_invents():
    error = await _query_parse_error(INDEX, BAD_DATE_MATH)
    assert error is not None
    assert "/M-1ms" in error


@pytest.mark.anyio
@pytest.mark.parametrize("expr,accepted", [
    # Unsupported unit — 5 of the 7 date-math failures in 1230 logged generations.
    ("now/M-1ms", False),
    ("now-1ms", False),
    ("now/M-1s", True),          # same shape, supported unit
    # A space anywhere kills it. The model wrote `now-1w/w + 5d/d` and ES said
    # "operator not supported for date math [-1w/w + 5d/d]".
    ("now-1w/w + 5d/d", False),
    ("now-1w/w+5d/d", True),
    # One unit per operation. `now/w-1d+23h59m59s` was another logged failure.
    ("now+23h59m59s", False),
    ("now-1d-1h", True),         # …several operations are fine
    # Rounding is legal on either side of the arithmetic.
    ("now/M-1d", True),
    ("now-1d/d", True),
])
async def test_what_es_date_math_actually_rejects(expr, accepted):
    """Pins every rule _REPAIR_PROMPT states, against a real ES.

    The prompt first claimed ES rejects "rounding, then arithmetic", citing
    `now/w-1d+23h59m59s` and `now-1w/w+5d/d`. Both are fine as written here —
    the real causes are the `ms` unit, an embedded space, and chaining units in
    one operation. A repair prompt stating a false rule steers the model off
    expressions that would have worked.
    """
    error = await _query_parse_error(INDEX, {"query": {"range": {"@timestamp": {"lt": expr}}}})
    assert (error is None) is accepted


@pytest.mark.anyio
async def test_es_accepts_the_correction():
    assert await _query_parse_error(INDEX, CORRECTED) is None


@pytest.mark.anyio
async def test_a_rejected_query_is_repaired_end_to_end(monkeypatch):
    """ES rejects → the model is re-asked → ES accepts the answer → it is returned."""
    router = _FixedRouter()
    monkeypatch.setattr("backend.llm.get_router", lambda: router)

    repaired = await repair_invalid_query(INDEX, [], BAD_DATE_MATH)

    assert repaired == CORRECTED
    assert len(router.calls) == 1, "exactly one corrective round-trip"
    assert "/M-1ms" in router.calls[0]["messages"][-1]["content"], "ES's own error is fed back"


@pytest.mark.anyio
async def test_a_valid_query_costs_no_round_trip(monkeypatch):
    """The pre-flight runs on every generation — it must stay free when nothing is wrong."""
    router = _FixedRouter()
    monkeypatch.setattr("backend.llm.get_router", lambda: router)

    assert await repair_invalid_query(INDEX, [], CORRECTED) is CORRECTED
    assert router.calls == []


@pytest.mark.anyio
async def test_a_correction_that_es_still_rejects_is_discarded(monkeypatch):
    """The model answering with something equally broken must not make things worse."""
    class _StillBroken(_FixedRouter):
        async def chat_completion(self, **kwargs):
            self.calls.append(kwargs)
            content = json.dumps({"dsl": STILL_BAD, "explanation": "x"}, ensure_ascii=False)
            choice = type("C", (), {"message": type("M", (), {"content": content})})
            return type("R", (), {"choices": [choice]}), None

    monkeypatch.setattr("backend.llm.get_router", lambda: _StillBroken())
    assert await repair_invalid_query(INDEX, [], BAD_DATE_MATH) is BAD_DATE_MATH
