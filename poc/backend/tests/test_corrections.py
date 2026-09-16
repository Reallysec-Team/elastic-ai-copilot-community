"""Corrections capture: lexical gate, distill contract, dedup, KB write.

No real LLM / ES / embedding calls — `get_router` and `get_kb` are
monkeypatched, mirroring test_solutions.py / test_rag_embed_gate.py's style.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import corrections  # noqa: E402


# ─────────────────────────── looks_like_correction ───────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "不对，登录失败是 4625 不是 4624",
        "不是这个字段，用 event.outcome",
        "错了，应该看 http_code",
        "转账失败要看 event_type=7 才是对的",
        "而不是 status=fail",
        "我是说要按天聚合",
        "我的意思是要看最近一周",
        "应该用 source.ip 不是 clientip",
        "别用 message 字段",
        "是 event_type=7，不是 status=fail",
        "不是，应该看 4740",
        "No, that's wrong, use event.code",
        "Actually the field is called event_type",
        "the answer should be event.outcome:failure",
        "I meant the last 7 days",
        "not status but event_type",
    ],
)
def test_looks_like_correction_positive(text):
    assert corrections.looks_like_correction(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "最近登录失败的事件",
        "统计一下过去一周的错误数",
        "帮我按小时聚合一下",
        "有多少条 5xx 的日志",
        "show me the recent failed logins",
        "how many errors in the last hour",
        # Measured false positives (see corrections.py's _ZH_MARKERS /
        # _BUJIAN_PATTERN comments) — these are common query shapes, not
        # corrections, and must stay negative.
        "哪些源 IP 不是内网地址",
        "注意力机制相关的日志",
        "统计不是 200 的响应码",
        "列出登录失败但不是 4625 的事件",
        "其实我想看昨天的",
        "记住我这个查询",
        "",
        "   ",
    ],
)
def test_looks_like_correction_negative(text):
    assert corrections.looks_like_correction(text) is False


# ─────────────────────────── distill ───────────────────────────


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


@pytest.mark.asyncio
async def test_distill_returns_none_when_not_durable(monkeypatch):
    router = _FakeRouter('{"durable": false, "title": "", "content": "", "reason": "只是反馈"}')
    monkeypatch.setattr(corrections, "get_router", lambda: router)
    result = await corrections.distill("这个不对")
    assert result is None


@pytest.mark.asyncio
async def test_distill_returns_none_on_llm_exception(monkeypatch):
    router = _FakeRouter(raises=RuntimeError("provider down"))
    monkeypatch.setattr(corrections, "get_router", lambda: router)
    result = await corrections.distill("转账失败要看 event_type=7")
    assert result is None


@pytest.mark.asyncio
async def test_distill_returns_none_on_non_json_output(monkeypatch):
    router = _FakeRouter("这不是 JSON，抱歉我不太理解")
    monkeypatch.setattr(corrections, "get_router", lambda: router)
    result = await corrections.distill("转账失败要看 event_type=7")
    assert result is None


@pytest.mark.asyncio
async def test_distill_truncates_oversized_output(monkeypatch):
    long_title = "标" * 200
    long_content = "内" * 2000
    payload = (
        '{"durable": true, "title": "' + long_title + '", "content": "' + long_content
        + '", "reason": "ok"}'
    )
    router = _FakeRouter(payload)
    monkeypatch.setattr(corrections, "get_router", lambda: router)
    result = await corrections.distill("转账失败要看 event_type=7")
    assert result is not None
    assert len(result["title"]) <= corrections._TITLE_MAX
    assert len(result["content"]) <= corrections._CONTENT_MAX


@pytest.mark.asyncio
async def test_distill_returns_fact_when_durable(monkeypatch):
    payload = '{"durable": true, "title": "转账失败字段", "content": "转账失败要看 event_type=7", "reason": "字段约定"}'
    router = _FakeRouter(payload)
    monkeypatch.setattr(corrections, "get_router", lambda: router)
    result = await corrections.distill("转账失败要看 event_type=7")
    assert result == {"title": "转账失败字段", "content": "转账失败要看 event_type=7"}


# ─────────────────────────── capture ───────────────────────────


class _FakeKB:
    def __init__(self, retrieve_hits=None, add_raises=None, retrieve_raises=None):
        self._retrieve_hits = retrieve_hits or []
        self._add_raises = add_raises
        self._retrieve_raises = retrieve_raises
        self.added: list = []

    async def retrieve(self, query, top_k=3):
        if self._retrieve_raises:
            raise self._retrieve_raises
        return self._retrieve_hits

    async def add_document(self, title, content, metadata=None):
        if self._add_raises:
            raise self._add_raises
        self.added.append({"title": title, "content": content, "metadata": metadata})
        return {"doc_id": "abc123"}


@pytest.mark.asyncio
async def test_capture_skips_llm_when_not_a_correction(monkeypatch):
    router = _FakeRouter('{"durable": true, "title": "x", "content": "y", "reason": "ok"}')
    monkeypatch.setattr(corrections, "get_router", lambda: router)
    kb = _FakeKB()
    monkeypatch.setattr(corrections, "get_kb", lambda: kb)

    result = await corrections.capture("最近登录失败的事件", owner="alice")

    assert result is None
    assert router.calls == 0
    assert kb.added == []


@pytest.mark.asyncio
async def test_capture_ungated_skips_lexical_gate(monkeypatch):
    # No marker words at all — would be rejected by looks_like_correction,
    # but the caller (e.g. thumbs-down "what was wrong?" box) already knows
    # this is a correction, so gated=False must still reach distill.
    payload = '{"durable": true, "title": "转账失败字段", "content": "转账失败对应 event_type=7", "reason": "字段约定"}'
    router = _FakeRouter(payload)
    monkeypatch.setattr(corrections, "get_router", lambda: router)
    kb = _FakeKB(retrieve_hits=[])
    monkeypatch.setattr(corrections, "get_kb", lambda: kb)

    assert corrections.looks_like_correction("转账失败对应 event_type=7") is False

    result = await corrections.capture("转账失败对应 event_type=7", owner="alice", gated=False)

    assert result == "abc123"
    assert router.calls == 1


@pytest.mark.asyncio
async def test_capture_skips_write_on_dedup_hit(monkeypatch):
    payload = '{"durable": true, "title": "转账失败字段", "content": "转账失败要看 event_type=7", "reason": "字段约定"}'
    router = _FakeRouter(payload)
    monkeypatch.setattr(corrections, "get_router", lambda: router)
    kb = _FakeKB(retrieve_hits=[
        {"metadata": {"source": "correction"}, "score": 0.95, "content": "转账失败要看 event_type=7"}
    ])
    monkeypatch.setattr(corrections, "get_kb", lambda: kb)

    result = await corrections.capture("不对，转账失败要看 event_type=7", owner="alice")

    assert result is None
    assert kb.added == []


@pytest.mark.asyncio
async def test_capture_writes_kb_with_expected_metadata(monkeypatch):
    payload = '{"durable": true, "title": "转账失败字段", "content": "转账失败要看 event_type=7", "reason": "字段约定"}'
    router = _FakeRouter(payload)
    monkeypatch.setattr(corrections, "get_router", lambda: router)
    kb = _FakeKB(retrieve_hits=[])
    monkeypatch.setattr(corrections, "get_kb", lambda: kb)

    result = await corrections.capture(
        "不对，转账失败要看 event_type=7", owner="alice", question="转账失败有哪些", index="txn-*"
    )

    assert result == "abc123"
    assert len(kb.added) == 1
    meta = kb.added[0]["metadata"]
    assert meta["source"] == "correction"
    assert meta["auto"] is True
    assert meta["owner"] == "alice"
    assert meta["question"] == "转账失败有哪些"
    assert meta["index"] == "txn-*"


@pytest.mark.asyncio
async def test_capture_returns_none_on_kb_write_failure(monkeypatch):
    payload = '{"durable": true, "title": "转账失败字段", "content": "转账失败要看 event_type=7", "reason": "字段约定"}'
    router = _FakeRouter(payload)
    monkeypatch.setattr(corrections, "get_router", lambda: router)
    kb = _FakeKB(add_raises=RuntimeError("es down"))
    monkeypatch.setattr(corrections, "get_kb", lambda: kb)

    result = await corrections.capture("不对，转账失败要看 event_type=7", owner="alice")

    assert result is None


@pytest.mark.asyncio
async def test_capture_returns_none_on_dedup_lookup_failure(monkeypatch):
    payload = '{"durable": true, "title": "转账失败字段", "content": "转账失败要看 event_type=7", "reason": "字段约定"}'
    router = _FakeRouter(payload)
    monkeypatch.setattr(corrections, "get_router", lambda: router)
    kb = _FakeKB(retrieve_raises=RuntimeError("es down"))
    monkeypatch.setattr(corrections, "get_kb", lambda: kb)

    # dedup lookup failure degrades to "no existing match found" rather than
    # blocking capture — best-effort throughout.
    result = await corrections.capture("不对，转账失败要看 event_type=7", owner="alice")

    assert result == "abc123"
