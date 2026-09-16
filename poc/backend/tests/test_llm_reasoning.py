"""推理强度（思考模式）跨供应商翻译 + 首字超时 —— 不碰真模型。

盯三件事：
  1. llm_reasoning 的翻译表：认识的家族发对的参数，不认识的什么都不发；
     provider 覆盖压过调用方意图。
  2. 路由把参数真塞进 chat.completions.create；被 400 就去掉参数原地重试。
  3. generate_dsl_stream 转发 reasoning_content 为 thinking 帧；正文迟迟不出
     → error 帧带 code=llm_first_token_timeout。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import llm, llm_reasoning  # noqa: E402
from backend.llm_router import LLMRouter, Provider  # noqa: E402


# ── 1. 翻译表 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("base_url,model,kind,family", [
    ("https://ark.cn-beijing.volces.com/api/coding/v3", "ark-code-latest", "openai", "ark"),
    ("https://ark.cn-beijing.volces.com/api/v3", "doubao-seed-1.6", "openai", "ark"),
    ("https://api.openai.com/v1", "gpt-5", "openai", "openai"),
    ("https://api.openai.com/v1", "gpt-4o", "openai", "openai"),
    ("https://res.openai.azure.com", "my-deployment", "azure", "openai"),
    ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3-235b", "openai", "dashscope"),
    ("https://api.deepseek.com", "deepseek-reasoner", "openai", "deepseek"),
    ("https://api.anthropic.com/v1/", "claude-sonnet-5", "openai", "anthropic"),
    ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-pro", "openai", "gemini"),
    ("https://openrouter.ai/api/v1", "anything", "openai", "openrouter"),
    ("http://10.0.0.5:8000/v1", "my-local-model", "openai", "unknown"),
])
def test_detect_family(base_url, model, kind, family):
    assert llm_reasoning.detect_family(base_url, model, kind) == family


def test_params_ark_none_disables_thinking():
    assert llm_reasoning.params_for("ark", "ark-code-latest", "none") == {
        "extra_body": {"thinking": {"type": "disabled"}}
    }
    # 豆包只有开 / 关，low 落在关。
    assert llm_reasoning.params_for("ark", "ark-code-latest", "low") == {
        "extra_body": {"thinking": {"type": "disabled"}}
    }
    assert llm_reasoning.params_for("ark", "ark-code-latest", "high") == {
        "extra_body": {"thinking": {"type": "enabled"}}
    }


def test_params_openai_only_for_reasoning_models():
    assert llm_reasoning.params_for("openai", "gpt-5", "none") == {"reasoning_effort": "minimal"}
    assert llm_reasoning.params_for("openai", "o3", "high") == {"reasoning_effort": "high"}
    # gpt-4o 收到 reasoning_effort 会 400 —— 什么都不发。
    assert llm_reasoning.params_for("openai", "gpt-4o", "none") == {}


def test_params_unknown_family_sends_nothing():
    for level in llm_reasoning.LEVELS:
        assert llm_reasoning.params_for("unknown", "x", level) == {}
        assert llm_reasoning.params_for("deepseek", "deepseek-chat", level) == {}


def test_resolve_provider_override_beats_hint():
    assert llm_reasoning.resolve("auto", "none") == "none"
    assert llm_reasoning.resolve("auto", None) is None
    assert llm_reasoning.resolve("off", "high") == "none"
    assert llm_reasoning.resolve("high", "none") == "high"
    assert llm_reasoning.resolve("garbage", "low") == "low"  # 非法覆盖 = auto


def test_merge_params_keeps_caller_extra_body():
    out = llm_reasoning.merge_params(
        {"extra_body": {"foo": 1}, "temperature": 0},
        {"extra_body": {"thinking": {"type": "disabled"}}},
    )
    assert out["extra_body"] == {"foo": 1, "thinking": {"type": "disabled"}}
    assert out["temperature"] == 0


# ── 2. 路由真把参数发出去；400 就退一步 ───────────────────────────────────────

class _Resp:
    choices = [1]


class _BadRequest(Exception):
    status_code = 400


class _FakeCompletions:
    def __init__(self, reject_reasoning: bool = False):
        self.calls: list[dict] = []
        self.reject_reasoning = reject_reasoning

    async def create(self, **kw):
        self.calls.append(kw)
        if self.reject_reasoning and ("extra_body" in kw or "reasoning_effort" in kw):
            raise _BadRequest("unknown parameter")
        if kw.get("stream"):
            async def _gen():
                yield object()
            return _gen()
        return _Resp()


class _FakeClient:
    def __init__(self, completions):
        self.chat = type("C", (), {"completions": completions})()


def _router(provider: Provider, completions: _FakeCompletions) -> LLMRouter:
    r = LLMRouter([provider])
    r._clients = {}
    r._get_client = lambda p: _FakeClient(completions)  # type: ignore[method-assign]
    return r


def _ark(reasoning: str = "auto") -> Provider:
    return Provider(
        id="ark", base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="k", model="ark-code-latest", reasoning=reasoning,
    )


def test_router_sends_translated_param():
    comp = _FakeCompletions()
    r = _router(_ark(), comp)
    asyncio.run(r.chat_completion(messages=[], reasoning="none"))
    assert comp.calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_router_provider_override_off_wins():
    comp = _FakeCompletions()
    r = _router(_ark(reasoning="off"), comp)
    asyncio.run(r.chat_completion(messages=[], reasoning="high"))
    assert comp.calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_router_no_hint_sends_nothing():
    comp = _FakeCompletions()
    r = _router(_ark(), comp)
    asyncio.run(r.chat_completion(messages=[]))
    assert "extra_body" not in comp.calls[0]


def test_router_retries_without_reasoning_on_400():
    comp = _FakeCompletions(reject_reasoning=True)
    r = _router(_ark(), comp)
    resp, _ = asyncio.run(r.chat_completion(messages=[], reasoning="none"))
    assert isinstance(resp, _Resp)
    assert len(comp.calls) == 2
    assert "extra_body" in comp.calls[0] and "extra_body" not in comp.calls[1]


def test_router_stream_retries_without_reasoning_on_400(monkeypatch):
    monkeypatch.setenv("RST_LLM_STREAM_USAGE", "0")
    comp = _FakeCompletions(reject_reasoning=True)
    r = _router(_ark(), comp)

    async def _drain():
        return [c async for c in r.chat_completion_stream(messages=[], reasoning="none")]

    assert len(asyncio.run(_drain())) == 1
    assert len(comp.calls) == 2 and "extra_body" not in comp.calls[1]


# ── 3. thinking 帧 + 首字超时 ────────────────────────────────────────────────

class _Delta:
    def __init__(self, content=None, reasoning_content=None):
        self.content = content
        self.reasoning_content = reasoning_content


class _Choice:
    def __init__(self, **kw):
        self.delta = _Delta(**kw)


class _Chunk:
    def __init__(self, **kw):
        self.choices = [_Choice(**kw)]
        self.usage = None


class _P:
    id = "fake"


def _collect(monkeypatch, router):
    monkeypatch.setattr("backend.llm.get_router", lambda: router)

    async def _run():
        return [ev async for ev in llm.generate_dsl_stream("q", "idx", {})]

    return asyncio.run(_run())


def test_stream_forwards_thinking_then_content(monkeypatch):
    class _R:
        async def chat_completion_stream(self, **kw):
            assert kw.get("reasoning") == "low"  # NL→DSL 默认 low
            yield _P(), _Chunk(reasoning_content="先看字段")
            yield _P(), _Chunk(reasoning_content="…")
            for ch in '{"dsl":{"size":0},"explanation":"ok","confidence":"high"}':
                yield _P(), _Chunk(content=ch)

    monkeypatch.delenv("RST_NL2DSL_REASONING", raising=False)
    events = _collect(monkeypatch, _R())
    thinking = [e for e in events if e["type"] == "thinking"]
    assert [e["text"] for e in thinking] == ["先看字段", "…"]
    done = [e for e in events if e["type"] == "done"]
    assert done and done[0]["dsl"] == {"size": 0}
    assert done[0]["thinking_chars"] == 5


def test_stream_first_token_timeout(monkeypatch):
    monkeypatch.setenv("RST_LLM_FIRST_TOKEN_TIMEOUT_S", "0.2")

    class _R:
        async def chat_completion_stream(self, **kw):
            # 只吐推理、永远不吐正文 —— 思考模型想过头的样子。
            for _ in range(50):
                await asyncio.sleep(0.05)
                yield _P(), _Chunk(reasoning_content="想…")

    events = _collect(monkeypatch, _R())
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "llm_first_token_timeout"
    assert any(e["type"] == "thinking" for e in events)  # 超时前的思考照样转发了


def test_stream_timeout_not_applied_once_content_started(monkeypatch):
    monkeypatch.setenv("RST_LLM_FIRST_TOKEN_TIMEOUT_S", "0.2")

    class _R:
        async def chat_completion_stream(self, **kw):
            yield _P(), _Chunk(content="{")
            await asyncio.sleep(0.4)  # 正文已开始，慢一点不算超时
            for ch in '"dsl":{"size":0},"explanation":"ok","confidence":"high"}':
                yield _P(), _Chunk(content=ch)

    events = _collect(monkeypatch, _R())
    assert events[-1]["type"] == "done"
