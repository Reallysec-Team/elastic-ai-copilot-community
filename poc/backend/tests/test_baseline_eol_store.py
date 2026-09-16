"""eol-catalog 索引读写单测（TDD）—— 全 mock ES，验证 DSL / bulk op 形状。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.baseline import eol_store  # noqa: E402


class _FakeES:
    def __init__(self, bulk_body=None):
        self.bulk_ops = None
        self.bulk_refresh = None
        self._bulk_body = bulk_body or {"errors": False, "items": []}

    async def bulk(self, operations, refresh=None):
        self.bulk_ops = operations
        self.bulk_refresh = refresh
        return type("R", (), {"body": self._bulk_body})()


def test_lookup_hit_returns_source(monkeypatch):
    async def _search(index, dsl):
        assert index == eol_store.EOL_CATALOG_INDEX
        # 必须按 product + cycle 精确过滤
        filters = dsl["query"]["bool"]["filter"]
        assert {"term": {"product": "centos"}} in filters
        assert {"term": {"cycle": "7"}} in filters
        return {"hits": {"hits": [{"_source": {"product": "centos", "cycle": "7", "eol_raw": "2024-06-30"}}]}}
    monkeypatch.setattr(eol_store, "execute_search", _search)
    entry = asyncio.run(eol_store.lookup("centos", "7"))
    assert entry["eol_raw"] == "2024-06-30"


def test_lookup_miss_returns_none(monkeypatch):
    async def _search(index, dsl):
        return {"hits": {"hits": []}}
    monkeypatch.setattr(eol_store, "execute_search", _search)
    assert asyncio.run(eol_store.lookup("centos", "999")) is None


def test_bulk_upsert_shapes_ops_with_doc_id(monkeypatch):
    fake = _FakeES()
    monkeypatch.setattr(eol_store, "get_es", lambda: fake)
    docs = [
        {"product": "centos", "cycle": "7", "eol_raw": "2024-06-30"},
        {"product": "ubuntu", "cycle": "22.04", "eol_raw": "false"},
    ]
    n = asyncio.run(eol_store.bulk_upsert(docs))
    assert n == 2
    # 交替的 action / doc；_id = product:cycle
    assert fake.bulk_ops[0] == {"index": {"_index": eol_store.EOL_CATALOG_INDEX, "_id": "centos:7"}}
    assert fake.bulk_ops[1] == docs[0]
    assert fake.bulk_ops[2] == {"index": {"_index": eol_store.EOL_CATALOG_INDEX, "_id": "ubuntu:22.04"}}
    assert fake.bulk_refresh == "wait_for"


def test_count_reads_total(monkeypatch):
    async def _search(index, dsl):
        assert index == eol_store.EOL_CATALOG_INDEX
        return {"hits": {"total": {"value": 42}}}
    monkeypatch.setattr(eol_store, "execute_search", _search)
    assert asyncio.run(eol_store.count()) == 42


def test_count_zero_when_index_missing(monkeypatch):
    async def _boom(index, dsl):
        raise RuntimeError("no such index")
    monkeypatch.setattr(eol_store, "execute_search", _boom)
    assert asyncio.run(eol_store.count()) == 0


def test_bulk_upsert_strips_none_fields(monkeypatch):
    fake = _FakeES()
    monkeypatch.setattr(eol_store, "get_es", lambda: fake)
    # eol=None（bool 值场景）→ 写入前剔除，避免 date 字段吃 null 报错
    docs = [{"product": "centos", "cycle": "6", "eol": None, "eol_raw": "true"}]
    asyncio.run(eol_store.bulk_upsert(docs))
    body = fake.bulk_ops[1]
    assert "eol" not in body
    assert body == {"product": "centos", "cycle": "6", "eol_raw": "true"}


def test_bulk_upsert_empty_is_noop(monkeypatch):
    called = {"bulk": False}
    fake = _FakeES()

    async def _bulk(operations, refresh=None):
        called["bulk"] = True
        return type("R", (), {"body": {"errors": False}})()
    fake.bulk = _bulk
    monkeypatch.setattr(eol_store, "get_es", lambda: fake)
    n = asyncio.run(eol_store.bulk_upsert([]))
    assert n == 0
    assert called["bulk"] is False
