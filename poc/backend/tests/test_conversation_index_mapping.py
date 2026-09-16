"""会话索引的 owner 字段不能靠动态映射长出来。

按人隔离的过滤走 `{"term": {"owner.keyword": …}}`。这个子字段以前是 ES 自己猜的 ——
客户那边只要有一个 index template 罩住这个索引名、把 owner 定成别的类型，过滤就
永远匹配不上：每个账号的历史列表恒空，而且不报错。analysis_store 已经踩过一次同样
的坑（那边现在有显式映射），这里补齐。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import conversation  # noqa: E402


class _FakeIndices:
    def __init__(self, exists: bool):
        self._exists = exists
        self.created: list[dict] = []

    async def exists(self, index):  # noqa: A002
        return self._exists

    async def create(self, index, body):  # noqa: A002
        self.created.append({"index": index, "body": body})


class _FakeES:
    def __init__(self, exists: bool = False):
        self.indices = _FakeIndices(exists)
        self.searched: list[dict] = []

    class _Body:
        def __init__(self, body):
            self.body = body

    async def search(self, index, body):  # noqa: A002
        self.searched.append(body)
        return self._Body({"hits": {"total": {"value": 0}, "hits": []}})


@pytest.fixture(autouse=True)
def _fresh():
    conversation._reset_index_ready_for_tests()
    yield
    conversation._reset_index_ready_for_tests()


def test_a_missing_index_is_created_with_owner_as_keyword():
    es = _FakeES(exists=False)
    asyncio.run(conversation._ensure_es_index(es))

    assert len(es.indices.created) == 1
    props = es.indices.created[0]["body"]["mappings"]["properties"]
    assert props["owner"]["type"] == "keyword"
    # 查询路径写的是 owner.keyword，新索引上也得有这个名字，否则老索引和新索引
    # 要分两条查询路径。
    assert props["owner"]["fields"]["keyword"]["type"] == "keyword"


def test_an_existing_index_is_left_alone():
    """老部署的动态映射索引不能被动 —— 那里已经有数据了。"""
    es = _FakeES(exists=True)
    asyncio.run(conversation._ensure_es_index(es))
    assert es.indices.created == []


def test_ensure_is_idempotent_after_the_first_call():
    es = _FakeES(exists=False)
    asyncio.run(conversation._ensure_es_index(es))
    asyncio.run(conversation._ensure_es_index(es))
    assert len(es.indices.created) == 1


def test_the_owner_filter_stays_on_the_keyword_subfield(monkeypatch):
    """两种索引共用一条查询路径。改成裸 `owner` 会在老索引上（text）变成分词匹配 ——
    既可能匹配不上，也可能匹配到别人。"""
    es = _FakeES(exists=True)
    monkeypatch.setattr(conversation, "get_es", lambda: es, raising=False)
    monkeypatch.setattr("backend.es_client.get_es", lambda: es)

    asyncio.run(conversation._es_list_all(10, 0, owner="alice"))

    filters = es.searched[0]["query"]["bool"]["filter"]
    assert {"term": {"owner.keyword": "alice"}} in filters
