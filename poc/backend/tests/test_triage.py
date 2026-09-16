"""Triage orchestration — clustering (pure) + degraded fallback (mock LLM)."""
from __future__ import annotations

import asyncio

import pytest
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import triage  # noqa: E402
from conftest import premium_core  # noqa: E402


@pytest.fixture(autouse=True)
def _needs_sealed_core():
    """聚类、评分合并、排名都在密封内核里；没有 premium_src 的 checkout 里整文件 skip。"""
    premium_core("alert_triage")


def test_cluster_alerts_groups_by_rule_subject():
    core = premium_core("alert_triage")
    alerts = [
        {"_id": "1", "_source": {"rule": {"id": "bruteforce"}, "source": {"ip": "1.1.1.1"}}},
        {"_id": "2", "_source": {"rule": {"id": "bruteforce"}, "source": {"ip": "1.1.1.1"}}},
        {"_id": "3", "_source": {"rule": {"id": "portscan"}, "source": {"ip": "2.2.2.2"}}},
    ]
    clusters = core["cluster_alerts"](alerts)
    assert sorted(c["count"] for c in clusters) == [1, 2]  # 2 distinct (rule, subject)


def test_triage_degraded_when_llm_fails(monkeypatch):
    async def _identity(prompt, **_kw):
        return prompt, 0

    class _BadRouter:
        async def chat_completion(self, **_kw):
            raise RuntimeError("llm down")

    monkeypatch.setattr("backend.triage.augment_prompt_meta", _identity)
    monkeypatch.setattr("backend.triage.get_router", lambda: _BadRouter())

    alerts = [{"_id": "1", "_source": {"rule": {"id": "r"}, "source": {"ip": "1.1.1.1"}}}]
    res = asyncio.run(triage.triage_alerts(alerts=alerts))
    # LLM scoring failed → degraded, but the clustering work is still returned.
    assert res["degraded"] is True
    assert res["total_clusters"] == 1
    assert len(res["clusters"]) == 1
    assert res["scored_clusters"] == 0


def test_triage_scores_when_llm_ok(monkeypatch):
    async def _identity(prompt, **_kw):
        return prompt, 0

    class _OkRouter:
        async def chat_completion(self, **_kw):
            # Minimal valid scoring for the single cluster.
            import json as _json

            class _Msg:
                content = _json.dumps(
                    {"clusters": [{"cluster_id": None, "severity": "high",
                                   "priority_rank": 1, "recommendation": "block ip",
                                   "is_likely_fp": False, "attack_intent": "暴力破解"}]}
                )

            class _Choice:
                message = _Msg()

            class _Resp:
                choices = [_Choice()]

            return _Resp(), object()

    monkeypatch.setattr("backend.triage.augment_prompt_meta", _identity)
    monkeypatch.setattr("backend.triage.get_router", lambda: _OkRouter())

    alerts = [{"_id": "1", "_source": {"rule": {"id": "r"}, "source": {"ip": "1.1.1.1"}}}]
    res = asyncio.run(triage.triage_alerts(alerts=alerts))
    assert res["degraded"] is False
    assert res["total_clusters"] == 1
    assert len(res["clusters"]) == 1


def test_triage_scores_in_chunks_and_degrades_only_the_failed_chunk(monkeypatch):
    """冷启动 2026-09-12：30 个聚类一次送模型，耗时随聚类数线性涨到超时，9 分钟
    后整批降级。现在按 RST_TRIAGE_LLM_CHUNK 分批并发；一批失败只影响那一批。"""
    import json as _json

    async def _identity(prompt, **_kw):
        return prompt, 0

    calls = []

    class _Router:
        async def chat_completion(self, messages, **_kw):
            calls.append(messages[1]["content"])
            if len(calls) == 2:
                raise TimeoutError("Request timed out.")

            class _Msg:
                content = _json.dumps({"clusters": [{"cluster_id": None, "severity": "high",
                                                     "priority_rank": 1, "recommendation": "x",
                                                     "is_likely_fp": False, "attack_intent": "y"}]})

            class _Choice:
                message = _Msg()

            class _Resp:
                choices = [_Choice()]

            return _Resp(), object()

    monkeypatch.setenv("RST_TRIAGE_LLM_CHUNK", "1")
    monkeypatch.setattr("backend.triage.augment_prompt_meta", _identity)
    monkeypatch.setattr("backend.triage.get_router", lambda: _Router())

    alerts = [{"_id": str(i), "_source": {"rule": {"id": f"r{i}"}, "source": {"ip": f"1.1.1.{i}"}}}
              for i in range(3)]
    res = asyncio.run(triage.triage_alerts(alerts=alerts))
    assert len(calls) == 3                      # one model call per chunk
    assert res["total_clusters"] == 3
    assert res["degraded"] is True
    assert "3 批评分里 1 批失败" in res["degraded_reason"]
    assert len(res["clusters"]) == 3            # nothing dropped
