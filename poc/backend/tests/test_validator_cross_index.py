"""DSL 校验：跨索引读取必须被拦下。

索引白名单只管请求"打向"哪个索引。ES 有两种查询形式会在此之外再去读第二个
索引的文档 —— 白名单从头到尾看不见它们。这两条路被堵死之后，白名单说的
"只能读这些索引"才是真的。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.validator import validate_dsl  # noqa: E402


@pytest.mark.parametrize("dsl", [
    {"query": {"terms": {"user": {"index": "secrets", "id": "1", "path": "token"}}}},
    # 藏在 bool 里，递归必须能走到
    {"query": {"bool": {"filter": [
        {"term": {"a": 1}},
        {"terms": {"user": {"index": "secrets", "id": "1", "path": "token"}}},
    ]}}},
])
def test_terms_lookup_rejected(dsl):
    with pytest.raises(ValueError, match="bypasses the index whitelist"):
        validate_dsl(dsl)


@pytest.mark.parametrize("like", [
    [{"_index": "secrets", "_id": "1"}],
    {"_index": "secrets", "_id": "1"},          # 单文档不裹 list
    ["free text", {"_index": "secrets"}],       # 混在正常文本里
])
def test_more_like_this_cross_index_rejected(like):
    with pytest.raises(ValueError, match="bypasses the index whitelist"):
        validate_dsl({"query": {"more_like_this": {"like": like}}})


def test_more_like_this_unlike_also_rejected():
    """unlike 跟 like 一样会去取文档，漏掉它等于没堵。"""
    with pytest.raises(ValueError, match="bypasses the index whitelist"):
        validate_dsl({"query": {"more_like_this": {"unlike": [{"_index": "secrets"}]}}})


@pytest.mark.parametrize("dsl", [
    {"query": {"terms": {"user": ["alice", "bob"]}}},
    {"aggs": {"top": {"terms": {"field": "host.name", "size": 10}}}},
    # 带 order 子对象的 terms 聚合 —— 值是 dict 但没有 index，不能误伤
    {"aggs": {"top": {"terms": {"field": "host.name", "order": {"_count": "desc"}}}}},
    {"query": {"more_like_this": {"like": "some text", "fields": ["message"]}}},
])
def test_normal_queries_still_pass(dsl):
    validate_dsl(dsl)
