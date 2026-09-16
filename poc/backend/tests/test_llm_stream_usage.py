"""Streaming token-usage capture (#14) — mock the router, no real LLM/ES.

Asserts generate_dsl_stream's `done` event carries the parsed DSL plus the token
usage extracted from the final usage-only chunk + output_chars.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import llm  # noqa: E402


class _Delta:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.delta = _Delta(content)


class _Chunk:
    def __init__(self, content=None, usage=None):
        self.choices = [_Choice(content)] if content is not None else []
        self.usage = usage


class _Usage:
    prompt_tokens = 100
    completion_tokens = 20
    total_tokens = 120


class _Provider:
    id = "fake"


class _Router:
    async def chat_completion_stream(self, **_kw):
        body = '{"dsl":{"size":0},"explanation":"ok","confidence":"high"}'
        for ch in body:
            yield _Provider(), _Chunk(content=ch)
        # Final usage-only chunk (empty choices) — the path that carries tokens.
        yield _Provider(), _Chunk(content=None, usage=_Usage())


def test_stream_done_carries_usage_and_dsl(monkeypatch):
    monkeypatch.setattr("backend.llm.get_router", lambda: _Router())

    async def _collect():
        out = []
        async for ev in llm.generate_dsl_stream("q", "idx", {}):
            out.append(ev)
        return out

    events = asyncio.run(_collect())
    done = [e for e in events if e.get("type") == "done"]
    assert len(done) == 1
    d = done[0]
    assert d["dsl"] == {"size": 0}
    assert d["confidence"] == "high"
    assert d["usage"] == {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    assert d["output_chars"] > 0
