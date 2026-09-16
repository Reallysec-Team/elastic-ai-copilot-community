"""RAG augment gate 认 yml 配置;index_dims 读现有索引维度。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import rag  # noqa: E402


@pytest.mark.asyncio
async def test_augment_short_circuits_when_not_configured(monkeypatch):
    monkeypatch.setattr(rag, "embedding_configured", lambda: False)
    prompt, used = await rag.augment_prompt_meta("hello")
    assert prompt == "hello" and used == 0


@pytest.mark.asyncio
async def test_augment_proceeds_when_configured_via_yml(monkeypatch):
    monkeypatch.setattr(rag, "embedding_configured", lambda: True)

    class _KB:
        async def ensure_index(self): pass
        async def retrieve(self, query, top_k): return []
    monkeypatch.setattr(rag, "get_kb", lambda: _KB())
    prompt, used = await rag.augment_prompt_meta("hello")
    # configured → it tried to retrieve (got 0 hits) rather than short-circuiting.
    assert used == 0


@pytest.mark.asyncio
async def test_index_dims_reads_existing_mapping(monkeypatch):
    class _ES:
        async def indices_get_mapping(self, *a, **k): ...
    class FakeES:
        class indices:
            @staticmethod
            async def get_mapping(index=None):
                return {index: {"mappings": {"properties": {"vector": {"dims": 2048}}}}}
    monkeypatch.setattr(rag, "get_es", lambda: FakeES())
    dims = await rag.get_kb().index_dims()
    assert dims == 2048


@pytest.mark.asyncio
async def test_index_dims_none_when_index_missing(monkeypatch):
    class FakeES:
        class indices:
            @staticmethod
            async def get_mapping(index=None):
                raise RuntimeError("index_not_found_exception")
    monkeypatch.setattr(rag, "get_es", lambda: FakeES())
    assert await rag.get_kb().index_dims() is None
