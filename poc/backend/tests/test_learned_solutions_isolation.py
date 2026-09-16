"""learned solutions 不再是「谁都能写、喂给所有人」的共享 few-shot。

两道：
  * 检索按主人过滤 —— 别人的例子不会进我的 NL→DSL few-shot；
  * viewer 的成功查询不进库 —— 只读账号不该有影响别人生成结果的写入权。

任一条单独都能挡住投毒，两条一起才谈得上纵深。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import solutions  # noqa: E402
from backend.tests.test_solutions import _FakeES  # noqa: E402


@pytest.fixture()
def _es(monkeypatch):
    fake = _FakeES()
    monkeypatch.setattr(solutions, "get_es", lambda: fake)
    monkeypatch.setattr(solutions, "embedding_configured", lambda: False)
    return fake


def _filters(kwargs) -> list:
    return kwargs["query"]["bool"]["filter"]


@pytest.mark.asyncio
async def test_find_similar_scopes_to_owner_when_given(_es):
    await solutions.find_similar("q", "idx", owner="alice")
    assert {"term": {"owner": "alice"}} in _filters(_es.last_search_kwargs)


@pytest.mark.asyncio
async def test_find_similar_without_owner_is_unscoped(_es):
    """留着不带 owner 的用法（离线评测、脚本），但产品路径一律带。"""
    await solutions.find_similar("q", "idx")
    assert all("owner" not in f.get("term", {}) for f in _filters(_es.last_search_kwargs))


@pytest.mark.asyncio
async def test_knn_path_also_carries_the_owner_filter(_es, monkeypatch):
    class _Embedder:
        async def embed_texts(self, texts):
            return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    monkeypatch.setattr(solutions, "embedding_configured", lambda: True)
    monkeypatch.setattr(solutions, "embed_dim", lambda: 4)
    monkeypatch.setattr(solutions, "get_embedding_client", lambda: _Embedder())

    await solutions.find_similar("q", "idx", owner="alice")

    knn_filters = _es.last_search_kwargs["knn"]["filter"]["bool"]["filter"]
    assert {"term": {"owner": "alice"}} in knn_filters
