"""KB augmentation on the main query path (`generate_dsl` / `generate_dsl_stream`).

The KB was wired into explain/investigate/triage/report/detection_rule but NOT
into DSL generation — the most-used feature — so anything a customer wrote in
their knowledge base had no effect on the queries we build for them.

No real LLM / ES / embedding calls: the router and `augment_prompt_meta` are
stubbed.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import llm, rag  # noqa: E402

_MAPPING = {"properties": {"event.code": {"type": "keyword"}}}


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Provider:
    id = "fake"


class _Router:
    """Captures the messages it was called with."""

    def __init__(self):
        self.messages = None

    async def chat_completion(self, messages, **_kw):
        self.messages = messages
        return _Resp('{"dsl":{"size":0},"explanation":"ok","confidence":"high"}'), _Provider()


def _fake_rag(marker: str, used: int = 2):
    async def _f(user_prompt, top_k=3, score_threshold=0.75, retrieval_query=None):
        _f.retrieval_query = retrieval_query
        _f.top_k = top_k
        return f"{marker}\n\n---\n\n{user_prompt}", used
    _f.retrieval_query = None
    return _f


def test_generate_dsl_prepends_kb_and_retrieves_on_the_question(monkeypatch):
    router = _Router()
    fake = _fake_rag("[KB] 转账失败 = event_type 7")
    monkeypatch.setattr("backend.llm.get_router", lambda: router)
    monkeypatch.setattr("backend.llm.augment_prompt_meta", fake)
    monkeypatch.setattr("backend.llm.repair_invalid_query",
                        lambda _idx, _msgs, dsl: _async(dsl))

    dsl, *_ = asyncio.run(llm.generate_dsl("最近的转账失败", "idx", _MAPPING))

    assert dsl == {"size": 0}
    user_msg = router.messages[-1]["content"]
    assert "[KB] 转账失败 = event_type 7" in user_msg
    # The KB block must sit ahead of the prompt body, not replace it.
    assert "索引: idx" in user_msg
    # Retrieval runs on the question, not on the mapping-heavy prompt head.
    assert fake.retrieval_query == "最近的转账失败"


def test_generate_dsl_stream_reports_rag_used(monkeypatch):
    class _Delta:
        def __init__(self, c):
            self.content = c

    class _SChoice:
        def __init__(self, c):
            self.delta = _Delta(c)

    class _Chunk:
        def __init__(self, c):
            self.choices = [_SChoice(c)]
            self.usage = None

    class _SRouter:
        def __init__(self):
            self.messages = None

        async def chat_completion_stream(self, messages, **_kw):
            self.messages = messages
            for ch in '{"dsl":null,"explanation":"ok","confidence":"low"}':
                yield _Provider(), _Chunk(ch)

    router = _SRouter()
    fake = _fake_rag("[KB] runbook", used=3)
    monkeypatch.setattr("backend.llm.get_router", lambda: router)
    monkeypatch.setattr("backend.llm.augment_prompt_meta", fake)

    async def _collect():
        return [ev async for ev in llm.generate_dsl_stream("问题", "idx", _MAPPING)]

    done = [e for e in asyncio.run(_collect()) if e.get("type") == "done"]
    assert len(done) == 1
    assert done[0]["rag_used"] == 3
    assert "[KB] runbook" in router.messages[-1]["content"]
    assert fake.retrieval_query == "问题"


def test_augment_uses_retrieval_query_when_given(monkeypatch):
    """rag.augment_prompt_meta searches on retrieval_query, augments user_prompt."""
    seen = {}

    class _KB:
        async def ensure_index(self, dims=None):
            pass

        async def retrieve(self, query, top_k=5, filter_doc_ids=None):
            seen["query"] = query
            return [{"title": "T", "content": "C", "score": 0.9}]

    monkeypatch.setattr(rag, "embedding_configured", lambda: True)
    monkeypatch.setattr(rag, "get_kb", lambda: _KB())

    prompt, used = asyncio.run(
        rag.augment_prompt_meta("LONG PROMPT BODY", retrieval_query="真正的问题")
    )
    assert seen["query"] == "真正的问题"
    assert used == 1
    assert "LONG PROMPT BODY" in prompt and "C" in prompt


def _async(value):
    async def _c():
        return value
    return _c()
