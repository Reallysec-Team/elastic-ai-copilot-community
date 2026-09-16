"""enrich.inventory —— 已导入资产/身份的只读一面：列表、搜索、覆盖率。

这个模块存在的前提是「不碰 resolver.py」，所以这里也不 import 它：匹配口径靠共用
`entity.normalize_*` 和同一组索引名来保证一致，测试盯的就是这份一致性。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.enrich import inventory  # noqa: E402
from backend.enrich.sources.csv_source import ASSETS_INDEX, IDENTITIES_INDEX  # noqa: E402


class FakeES:
    """按索引名分发的替身。search 收到什么 body 也记下来，供断言查询形状。"""

    def __init__(self, docs=None, aggs=None, counts=None):
        self.docs = docs or {}          # index -> list[_source]
        self.aggs = aggs or {}          # index -> list[key]（terms 聚合回的桶）
        self.counts = counts or {}      # index -> int
        self.bodies = []                # [(index, body)]

    async def search(self, index=None, body=None):
        self.bodies.append((index, body))
        if body.get("size") == 0 and "aggs" in body:
            keys = self.aggs.get(index, [])
            asked = set(body["query"]["terms"][next(iter(body["query"]["terms"]))])
            buckets = [{"key": k, "doc_count": 1} for k in keys if k in asked]
            return {"hits": {"total": {"value": 0}, "hits": []},
                    "aggregations": {"present": {"buckets": buckets}}}
        rows = self.docs.get(index, [])
        frm = body.get("from", 0)
        size = body.get("size", 10)
        window = rows[frm:frm + size]
        return {"hits": {"total": {"value": len(rows)},
                         "hits": [{"_id": f"id{i}", "_source": r}
                                  for i, r in enumerate(window)]}}

    async def count(self, index=None):
        if index not in self.counts:
            raise RuntimeError("index_not_found_exception")
        return {"count": self.counts[index]}


def _asset(name, host=None, ip=None):
    d = {"name": name, "criticality": "high", "owner": "张三", "department": "运维部"}
    if host:
        d["keys"] = [host]
    if ip:
        d["ip"] = ip
    return d


# ─────────────────────────────── 列表 ───────────────────────────────


@pytest.mark.asyncio
async def test_list_returns_rows_with_id_and_total():
    es = FakeES(docs={ASSETS_INDEX: [_asset("财务DB-01", host="win-db01"),
                                     _asset("Web-07", host="web-07")]})
    r = await inventory.list_entries("assets", None, 50, 0, es)
    assert r["total"] == 2
    assert [x["name"] for x in r["rows"]] == ["财务DB-01", "Web-07"]
    assert r["rows"][0]["id"] == "id0"
    assert r["next"] is None


@pytest.mark.asyncio
async def test_list_pages_with_after_offset():
    es = FakeES(docs={ASSETS_INDEX: [_asset(f"a{i}") for i in range(5)]})
    r = await inventory.list_entries("assets", None, 2, 0, es)
    assert [x["name"] for x in r["rows"]] == ["a0", "a1"]
    assert r["next"] == 2

    r = await inventory.list_entries("assets", None, 2, 4, es)
    assert [x["name"] for x in r["rows"]] == ["a4"]
    assert r["next"] is None          # 最后一页不再给下一页


@pytest.mark.asyncio
async def test_list_search_hits_join_keys_too():
    """排障时手里往往只有一个主机名 —— 它必须能搜。"""
    es = FakeES(docs={ASSETS_INDEX: []})
    await inventory.list_entries("assets", "win-db01", 50, 0, es)
    _, body = es.bodies[-1]
    fields = body["query"]["simple_query_string"]["fields"]
    assert {"keys", "ip", "user_key"} <= set(fields)
    assert "name" in fields


@pytest.mark.asyncio
async def test_list_blank_query_is_not_a_filter():
    es = FakeES(docs={ASSETS_INDEX: []})
    await inventory.list_entries("assets", "   ", 50, 0, es)
    _, body = es.bodies[-1]
    assert body["query"] == {"match_all": {}}


@pytest.mark.asyncio
async def test_list_identities_reads_the_identity_index():
    es = FakeES(docs={IDENTITIES_INDEX: [{"name": "李四", "user_key": "lisi"}]})
    r = await inventory.list_entries("identities", None, 50, 0, es)
    assert r["total"] == 1
    assert es.bodies[-1][0] == IDENTITIES_INDEX


@pytest.mark.asyncio
async def test_list_rejects_unknown_kind():
    with pytest.raises(ValueError):
        await inventory.list_entries("servers", None, 50, 0, FakeES())


@pytest.mark.asyncio
async def test_missing_index_is_empty_not_an_error():
    """一次都没导过 = 索引不存在。那不是错误，是「还没有数据」。"""
    class Boom(FakeES):
        async def search(self, index=None, body=None):
            raise RuntimeError("index_not_found_exception")

    r = await inventory.list_entries("assets", None, 50, 0, Boom())
    assert r == {"total": 0, "rows": [], "next": None}


# ────────────────────────────── 覆盖率 ──────────────────────────────


class CoverageES(FakeES):
    """告警索引单独一份：覆盖率要先抽样告警，再回表查。"""

    def __init__(self, alerts, aggs, alerts_index):
        super().__init__(aggs=aggs)
        self.alerts = alerts
        self.alerts_index = alerts_index

    async def search(self, index=None, body=None):
        if index == self.alerts_index:
            self.bodies.append((index, body))
            return {"hits": {"total": {"value": len(self.alerts)},
                             "hits": [{"_source": a} for a in self.alerts]}}
        return await super().search(index=index, body=body)


@pytest.fixture
def alerts_index(monkeypatch):
    monkeypatch.setattr(inventory, "_alerts_index", lambda: ".alerts-test")
    return ".alerts-test"


@pytest.mark.asyncio
async def test_coverage_counts_only_alerts_that_have_a_subject(alerts_index):
    """没有主体的告警不进分母 —— 它本来就无从匹配，算进去会把比例压成改不动的数。"""
    alerts = [
        {"subject_field": "host.name", "subject_value": "win-db01.corp.local"},
        {"subject_field": "user.name", "subject_value": "svc_backup"},
        {"subject_field": "", "subject_value": ""},          # 没主体
        {"subject_field": "host.name", "subject_value": "unknown-host"},
    ]
    es = CoverageES(alerts,
                    aggs={ASSETS_INDEX: ["win-db01.corp.local", "win-db01"],
                          IDENTITIES_INDEX: ["svc_backup"]},
                    alerts_index=alerts_index)
    r = await inventory.coverage(es)
    assert r["sampled"] == 4
    assert r["with_subject"] == 3
    assert r["matched"] == 2
    assert r["ratio"] == round(2 / 3, 3)


@pytest.mark.asyncio
async def test_coverage_routes_each_subject_kind_to_the_same_field_as_lookup(alerts_index):
    """字段口径必须和 sources/csv_source.lookup 一致，否则覆盖率会说谎。"""
    alerts = [
        {"subject_field": "host.name", "subject_value": "web-07"},
        {"subject_field": "source.ip", "subject_value": "203.0.113.77"},
        {"subject_field": "user.name", "subject_value": "root"},
    ]
    es = CoverageES(alerts, aggs={}, alerts_index=alerts_index)
    await inventory.coverage(es)
    asked = {
        (index, next(iter(body["query"]["terms"])))
        for index, body in es.bodies
        if index != alerts_index
    }
    assert (ASSETS_INDEX, "keys.keyword") in asked
    assert (ASSETS_INDEX, "ip.keyword") in asked
    assert (IDENTITIES_INDEX, "user_key.keyword") in asked


@pytest.mark.asyncio
async def test_coverage_with_no_alerts_reports_none_not_zero(alerts_index):
    """一条告警都没有时，覆盖率是「说不上来」，不是 0% —— 后者读起来像导入失败。"""
    es = CoverageES([], aggs={}, alerts_index=alerts_index)
    r = await inventory.coverage(es)
    assert r["ratio"] is None
    assert r["matched"] == 0


@pytest.mark.asyncio
async def test_summary_counts_missing_index_as_zero(alerts_index):
    es = CoverageES([], aggs={}, alerts_index=alerts_index)
    es.counts = {ASSETS_INDEX: 12}          # 身份表还没导过
    r = await inventory.summary(es)
    assert r["counts"] == {"assets": 12, "identities": 0}
    assert r["coverage"]["ratio"] is None
