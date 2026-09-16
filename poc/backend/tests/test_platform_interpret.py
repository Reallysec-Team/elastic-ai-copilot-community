"""Platform health interpretation: healthy-report short-circuit, normal
parse path, and the degrade path staying useful.

No real LLM / ES / embedding calls — `get_router` and `augment_prompt_meta`
are monkeypatched, mirroring test_corrections.py / test_solutions.py's style.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.platform_ops import interpret  # noqa: E402
from conftest import premium_core  # noqa: E402


@pytest.fixture(autouse=True)
def _needs_sealed_core():
    """这个文件测的是密封内核驱动的能力；没有 premium_src 的 checkout 里整文件 skip。"""
    premium_core("platform_ops_copilot")


class _FakeChoice:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeRouter:
    def __init__(self, content=None, raises=None):
        self._content = content
        self._raises = raises
        self.calls = 0

    async def chat_completion(self, **kwargs):
        self.calls += 1
        if self._raises:
            raise self._raises
        return _FakeResp(self._content), None


def _ok_report():
    return {
        "verdict": "ok",
        "counts": {"ok": 6, "warn": 0, "fail": 0, "unknown": 0},
        "checks": [
            {"id": "cluster_health", "title": "集群健康状态", "verdict": "ok", "summary": "绿色", "advice": ""},
        ],
    }


def _problem_report():
    return {
        "verdict": "fail",
        "counts": {"ok": 4, "warn": 1, "fail": 1, "unknown": 0},
        "checks": [
            {"id": "cluster_health", "title": "集群健康状态", "verdict": "ok", "summary": "绿色", "advice": ""},
            {
                "id": "disk_watermark", "title": "磁盘水位与只读块", "verdict": "fail",
                "summary": "发现 2 个索引被磁盘水位触发为只读。",
                "advice": "请先清理磁盘空间或扩容。",
            },
            {
                "id": "ingest_freshness", "title": "日志接入新鲜度", "verdict": "warn",
                "summary": "logs-system.security-default 最后写入超过阈值(612.8h)。",
                "advice": "请检查采集端是否在运行。",
            },
        ],
    }


async def _no_rag(user_prompt, top_k=3, retrieval_query=None, **kwargs):
    return user_prompt, 0


@pytest.mark.asyncio
async def test_interpret_skips_llm_when_all_ok(monkeypatch):
    router = _FakeRouter('{"conclusion": "should not be used", "actions": []}')
    monkeypatch.setattr(interpret, "get_router", lambda: router)
    monkeypatch.setattr(interpret, "augment_prompt_meta", _no_rag)

    result = await interpret.interpret(_ok_report())

    assert router.calls == 0
    assert result["conclusion"] == "各项检查正常，未发现需要处理的问题。"
    assert result["actions"] == []
    assert result["degraded"] is False
    assert result["rag_chunks_used"] == 0


@pytest.mark.asyncio
async def test_interpret_normal_path_passes_through_fields(monkeypatch):
    payload = (
        '{"conclusion": "磁盘水位触发只读导致该数据流停止写入，是同一件事。",'
        ' "actions": [{"title": "确认磁盘用量", "why": "只读块是根因", "how": "GET /_cat/allocation?v"}]}'
    )
    router = _FakeRouter(payload)
    monkeypatch.setattr(interpret, "get_router", lambda: router)

    async def rag(user_prompt, top_k=3, retrieval_query=None, **kwargs):
        return user_prompt, 2

    monkeypatch.setattr(interpret, "augment_prompt_meta", rag)

    result = await interpret.interpret(_problem_report())

    assert router.calls == 1
    assert result["degraded"] is False
    assert result["rag_chunks_used"] == 2
    assert "只读" in result["conclusion"]
    assert result["actions"] == [
        {"title": "确认磁盘用量", "why": "只读块是根因", "how": "GET /_cat/allocation?v"}
    ]


@pytest.mark.asyncio
async def test_interpret_degrades_on_llm_exception(monkeypatch):
    router = _FakeRouter(raises=RuntimeError("provider down"))
    monkeypatch.setattr(interpret, "get_router", lambda: router)
    monkeypatch.setattr(interpret, "augment_prompt_meta", _no_rag)

    result = await interpret.interpret(_problem_report())

    assert result["degraded"] is True
    assert result["conclusion"]
    assert len(result["actions"]) >= 1
    # fail-verdict check must sort before the warn-verdict check.
    assert result["actions"][0]["title"] == "磁盘水位与只读块"


@pytest.mark.asyncio
async def test_interpret_degrades_on_non_json_output(monkeypatch):
    router = _FakeRouter("这不是 JSON")
    monkeypatch.setattr(interpret, "get_router", lambda: router)
    monkeypatch.setattr(interpret, "augment_prompt_meta", _no_rag)

    result = await interpret.interpret(_problem_report())

    assert result["degraded"] is True
    assert result["conclusion"]
    assert len(result["actions"]) >= 1


@pytest.mark.asyncio
async def test_interpret_truncates_oversized_output(monkeypatch):
    long_conclusion = "结" * 1000
    actions = [
        {"title": "标" * 200, "why": "由" * 1000, "how": "步" * 1000}
        for _ in range(10)
    ]
    import json as _json
    payload = _json.dumps({"conclusion": long_conclusion, "actions": actions}, ensure_ascii=False)
    router = _FakeRouter(payload)
    monkeypatch.setattr(interpret, "get_router", lambda: router)
    monkeypatch.setattr(interpret, "augment_prompt_meta", _no_rag)

    result = await interpret.interpret(_problem_report())

    assert result["degraded"] is False
    assert len(result["conclusion"]) <= interpret._CONCLUSION_MAX
    assert len(result["actions"]) <= interpret._ACTIONS_MAX
    for a in result["actions"]:
        assert len(a["title"]) <= interpret._TITLE_MAX
        assert len(a["why"]) <= interpret._WHY_MAX
        assert len(a["how"]) <= interpret._HOW_MAX


@pytest.mark.asyncio
async def test_interpret_retrieval_query_excludes_ok_checks(monkeypatch):
    router = _FakeRouter('{"conclusion": "ok", "actions": []}')
    monkeypatch.setattr(interpret, "get_router", lambda: router)

    captured = {}

    async def rag(user_prompt, top_k=3, retrieval_query=None, **kwargs):
        captured["retrieval_query"] = retrieval_query
        return user_prompt, 0

    monkeypatch.setattr(interpret, "augment_prompt_meta", rag)

    await interpret.interpret(_problem_report())

    query = captured["retrieval_query"]
    assert "磁盘水位与只读块" in query
    assert "日志接入新鲜度" in query
    assert "集群健康状态" not in query
    assert len(query) <= interpret._RETRIEVAL_QUERY_MAX


@pytest.mark.asyncio
async def test_interpret_rag_chunks_used_passthrough(monkeypatch):
    router = _FakeRouter('{"conclusion": "ok", "actions": []}')
    monkeypatch.setattr(interpret, "get_router", lambda: router)

    async def rag(user_prompt, top_k=3, retrieval_query=None, **kwargs):
        return user_prompt, 5

    monkeypatch.setattr(interpret, "augment_prompt_meta", rag)

    result = await interpret.interpret(_problem_report())

    assert result["rag_chunks_used"] == 5
