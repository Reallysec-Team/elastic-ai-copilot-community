"""POST /api/explain-result — interpret a whole result set, not one document.

The gap this closes: a `size:0` aggregation answer renders as a bare table of
numbers with no next step. These tests pin the contract that makes the feature
useful — the model actually receives the aggregation buckets and the total (so
it can spot low agg coverage), subject values are masked on the way in, and the
endpoint refuses a request with nothing to interpret.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import explain, main  # noqa: E402
from backend import prompts  # noqa: E402

_DSL = {
    "size": 0,
    "query": {"bool": {"filter": [{"range": {"@timestamp": {"gte": "now-1h"}}}]}},
    "aggs": {"failures_by_source_ip": {"terms": {"field": "source.ip", "size": 10}}},
}
_AGGS = {
    "failures_by_source_ip": {
        "buckets": [
            {"key": "10.252.121.4", "doc_count": 1390},
            {"key": "10.145.188.22", "doc_count": 607},
        ]
    }
}


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def captured(monkeypatch):
    """Stub the LLM leg; capture what the model was actually asked."""
    seen: dict = {}

    async def fake_run(system, user_prompt, fallback):
        seen["system"] = system
        seen["user"] = user_prompt
        return {
            "summary": "s", "log_type": "认证失败统计", "key_fields": [],
            "indicators": [], "investigation": [], "severity": "info",
            "confidence": "low", "degraded": False, "rag_chunks_used": 0,
        }

    monkeypatch.setattr(explain, "_run", fake_run)
    return seen


def test_aggregations_and_total_reach_the_model(client, captured):
    """Coverage checks are the point — the model can't spot 'top buckets cover
    0.4% of hits' unless both the buckets and the total are in the prompt."""
    r = client.post(
        "/api/explain-result",
        json={
            "index": "logs-system.security.default",
            "question": "当前是否有黑客攻击在攻击业务系统?",
            "dsl": _DSL,
            "aggregations": _AGGS,
            "total": 689753,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["log_type"] == "认证失败统计"

    prompt = captured["user"]
    assert "当前是否有黑客攻击" in prompt
    assert "689753" in prompt              # total, for the coverage sanity check
    assert "failures_by_source_ip" in prompt
    assert "1390" in prompt                # bucket counts, not just names
    assert "failures_by_source_ip" in prompt
    # The system prompt must be the result flavour, not the single-log one.
    assert captured["system"] == prompts.explain_result_system_prompt()


def test_sample_hits_are_masked_and_capped(client, captured, monkeypatch):
    """Sample docs go through the same masking as everywhere else, and the
    server caps them regardless of what the client sends."""
    monkeypatch.setattr(explain, "mask_doc", lambda d: {**d, "user.name": "MASKED"})

    r = client.post(
        "/api/explain-result",
        json={
            "dsl": {"size": 5, "query": {"match_all": {}}},
            "sample_hits": [{"user.name": "alice", "n": i} for i in range(5)],
        },
    )
    assert r.status_code == 200, r.text
    prompt = captured["user"]
    assert "alice" not in prompt
    assert "MASKED" in prompt


def test_rejects_request_with_nothing_to_interpret(client):
    # No aggregations and no sample hits — there is no result to explain.
    r = client.post("/api/explain-result", json={"dsl": _DSL})
    assert r.status_code == 400
    # Missing dsl entirely is a schema error.
    assert client.post("/api/explain-result", json={}).status_code == 422


def test_over_cap_sample_hits_rejected_by_schema(client):
    r = client.post(
        "/api/explain-result",
        json={"dsl": _DSL, "sample_hits": [{"n": i} for i in range(9)]},
    )
    assert r.status_code == 422


def test_archive_derives_a_readable_row_for_a_result_explain():
    """The archive list shows `log_type` as the title and the question as the
    subject — without these a saved interpretation is an untitled blob."""
    from backend import analysis_store

    d = analysis_store._derive("result_explain", {
        "log_type": "无攻击相关有效信号",
        "summary": "近1小时内状态码400及以上的日志命中数为0。",
        "severity": "info",
        "question": "当前是否有黑客攻击在攻击业务系统?",
    })
    assert d["title"] == "无攻击相关有效信号"
    assert d["summary"].startswith("近1小时")
    assert d["severity"] == "info"
    assert d["subject"] == {"type": "query", "value": "当前是否有黑客攻击在攻击业务系统?"}


def test_archive_row_survives_a_result_explain_with_nothing_useful():
    from backend import analysis_store

    d = analysis_store._derive("result_explain", {})
    assert d["title"] == "查询结果解读"      # never blank in the list
    assert d["severity"] == "info"          # unknown severity must not leak through
