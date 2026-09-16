"""embeddings.py 探针 + 客户端解析优先级。用 monkeypatch 替 AsyncOpenAI,不触网。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import embeddings  # noqa: E402
from backend.llm_router import LLMRouter, Provider  # noqa: E402


class _FakeEmb:
    def __init__(self, dim):
        self._dim = dim
    async def create(self, model=None, input=None):
        class D:
            def __init__(s, v): s.embedding = v; s.index = 0
        return type("R", (), {"data": [D([0.1] * self._dim)]})()


class _FakeClient:
    def __init__(self, dim=1024, **kw):
        self.embeddings = _FakeEmb(dim)
        self.kwargs = kw


@pytest.fixture(autouse=True)
def _reset():
    embeddings.reset()
    yield
    embeddings.reset()


def test_resolve_endpoint_fills_from_chat_provider(monkeypatch):
    r = LLMRouter([Provider(id="a", base_url="http://chat", api_key="ck", model="m")])
    monkeypatch.setattr(embeddings, "get_router", lambda: r)
    base, key = embeddings.resolve_endpoint("", "")
    assert base == "http://chat" and key == "ck"


def test_resolve_endpoint_keeps_explicit_values(monkeypatch):
    r = LLMRouter([Provider(id="a", base_url="http://chat", api_key="ck", model="m")])
    monkeypatch.setattr(embeddings, "get_router", lambda: r)
    base, key = embeddings.resolve_endpoint("http://emb", "ek")
    assert base == "http://emb" and key == "ek"


def test_resolve_endpoint_raises_when_no_base_and_no_provider(monkeypatch):
    monkeypatch.setattr(embeddings, "get_router", lambda: LLMRouter([]))
    with pytest.raises(RuntimeError):
        embeddings.resolve_endpoint("", "")


@pytest.mark.asyncio
async def test_probe_returns_real_dim(monkeypatch):
    monkeypatch.setattr(embeddings, "AsyncOpenAI", lambda **kw: _FakeClient(dim=2048, **kw))
    monkeypatch.setattr(embeddings, "resolve_endpoint", lambda b, k: ("http://emb", "ek"))
    dim = await embeddings.probe_embedding("doubao-embed", "http://emb", "ek")
    assert dim == 2048


@pytest.mark.asyncio
async def test_probe_propagates_error(monkeypatch):
    class Boom:
        def __init__(self, **kw): pass
        @property
        def embeddings(self):
            class E:
                async def create(self, **kw): raise RuntimeError("401 unauthorized")
            return E()
    monkeypatch.setattr(embeddings, "AsyncOpenAI", lambda **kw: Boom(**kw))
    monkeypatch.setattr(embeddings, "resolve_endpoint", lambda b, k: ("http://emb", "ek"))
    with pytest.raises(RuntimeError, match="401"):
        await embeddings.probe_embedding("m", "http://emb", "ek")


def test_embed_model_prefers_yml(monkeypatch):
    monkeypatch.setattr(embeddings, "load_embedding_config",
                        lambda: {"model": "yml-model", "base_url": "", "api_key": "", "dims": 8, "enabled": True})
    monkeypatch.setenv("RST_EMBED_MODEL", "env-model")
    assert embeddings._embed_model() == "yml-model"


def test_embed_model_falls_back_to_env(monkeypatch):
    monkeypatch.setattr(embeddings, "load_embedding_config", lambda: None)
    monkeypatch.setenv("RST_EMBED_MODEL", "env-model")
    assert embeddings._embed_model() == "env-model"


def test_embed_dim_prefers_yml(monkeypatch):
    monkeypatch.setattr(embeddings, "load_embedding_config",
                        lambda: {"model": "m", "base_url": "", "api_key": "", "dims": 2048, "enabled": True})
    monkeypatch.setenv("RST_EMBED_DIM", "768")
    assert embeddings.embed_dim() == 2048


def test_embed_dim_falls_back_to_env(monkeypatch):
    monkeypatch.setattr(embeddings, "load_embedding_config", lambda: None)
    monkeypatch.setenv("RST_EMBED_DIM", "768")
    assert embeddings.embed_dim() == 768


def test_embed_model_ignores_disabled_yml(monkeypatch):
    monkeypatch.setattr(embeddings, "load_embedding_config",
                        lambda: {"model": "yml-model", "base_url": "", "api_key": "", "dims": 8, "enabled": False})
    monkeypatch.setenv("RST_EMBED_MODEL", "env-model")
    assert embeddings._embed_model() == "env-model"   # disabled yml → fall through to env


def test_embed_dim_ignores_disabled_yml(monkeypatch):
    monkeypatch.setattr(embeddings, "load_embedding_config",
                        lambda: {"model": "m", "base_url": "", "api_key": "", "dims": 2048, "enabled": False})
    monkeypatch.setenv("RST_EMBED_DIM", "768")
    assert embeddings.embed_dim() == 768              # disabled yml → fall through to env


def test_client_uses_yml_config(monkeypatch):
    monkeypatch.setattr(embeddings, "load_embedding_config",
                        lambda: {"model": "m", "base_url": "http://emb", "api_key": "ek", "dims": 8, "enabled": True})
    monkeypatch.setattr(embeddings, "resolve_endpoint", lambda b, k: (b or "x", k or "y"))
    monkeypatch.setattr(embeddings, "AsyncOpenAI", lambda **kw: _FakeClient(**kw))
    c = embeddings.EmbeddingClient()._get_client()
    assert c.kwargs["base_url"] == "http://emb" and c.kwargs["api_key"] == "ek"
