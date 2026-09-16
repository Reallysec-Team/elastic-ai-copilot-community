"""归档列表的 owner 过滤必须打在真实存在的字段上。

回归的是这个 bug：列表查的是 `owner.keyword`，而 `_INDEX_MAPPING` 把 owner 显式
声明成 keyword、没有 .keyword 子字段。查一个不存在的字段在真 ES 上永远匹配不到，
于是归档列表对所有人恒返回空 —— 而详情接口走 Python 侧比对，拿着 ID 又能打开。

所以替身按 `_INDEX_MAPPING` 解析 term 的字段名：映射里没有的字段一律不匹配。
写不进去的断言（普通 stub 只会照单全收）才是这个测试存在的理由。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import analysis_store  # noqa: E402


class _Indices:
    async def exists(self, index=None):
        return True

    async def create(self, index=None, body=None):  # pragma: no cover - 索引已存在
        raise AssertionError("index already exists")


class MappingAwareES:
    """按显式映射行事的 ES 替身：term 打在映射里没有的字段上 = 零命中。"""

    def __init__(self):
        self.docs: list[dict] = []
        self.indices = _Indices()
        self._props = analysis_store._INDEX_MAPPING["mappings"]["properties"]

    async def index(self, index=None, id=None, document=None, refresh=None):
        self.docs.append(document)
        return {"result": "created"}

    def _match(self, doc, f):
        if "term" in f:
            field, value = next(iter(f["term"].items()))
            if field not in self._props:
                return False  # 真 ES 也是这个结果：字段不存在，term 不匹配
            return doc.get(field) == value
        if "range" in f:
            field, r = next(iter(f["range"].items()))
            v = doc.get(field)
            if v is None:
                return False
            if "gte" in r and v < r["gte"]:
                return False
            if "lt" in r and v >= r["lt"]:
                return False
        return True

    async def search(self, index=None, body=None):
        hits = [d for d in self.docs
                if all(self._match(d, f) for f in body["query"]["bool"]["filter"])]
        hits.sort(key=lambda d: d["created_at"], reverse=True)
        return {"hits": {"total": {"value": len(hits)},
                         "hits": [{"_source": d} for d in hits[: body["size"]]]}}


@pytest.mark.asyncio
async def test_recorded_owner_is_listable_by_the_same_owner():
    es = MappingAwareES()
    rec_id = await analysis_store.record(
        "investigation",
        {"alert_type": "SSH 暴力破解", "summary": "多次失败登录", "severity": "high"},
        owner="alice", es=es)
    assert rec_id

    mine = await analysis_store.list_records(None, 50, None, "alice", es=es)
    assert [r["id"] for r in mine["records"]] == [rec_id]
    assert mine["total"] == 1

    others = await analysis_store.list_records(None, 50, None, "bob", es=es)
    assert others["records"] == []
