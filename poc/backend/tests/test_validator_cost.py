"""DSL 校验：命中数和聚合桶数的上限。

原来这一层只有节点数上限（`_MAX_NODES`）。它拦得住「一个巨大的查询体」，拦不住
「一个很小但很贵的查询」—— `size: 10000` 加两层高基数 terms 聚合，请求体几百
字节，ES 那边要建十万个桶。

最坏情况本来就被 ES 自己的 `max_result_window` / `search.max_buckets` 兜着，所以
不是无界；但在 ES 默认上限之内仍然构造得出很贵的查询，而 `/api/execute` 是把用户
给的 DSL 原样转发的。这组测试钉的就是网关这一层自己的那道防线。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.validator import validate_dsl  # noqa: E402


# ---------------------------------------------------------------- 命中数

def test_size_within_cap_passes():
    validate_dsl({"size": 1000})


@pytest.mark.parametrize("dsl", [
    {"size": 10000},
    # from+size 才是 ES 的 max_result_window 管的东西：深翻页跟一次取一万同样贵。
    {"from": 9990, "size": 100},
    # 模型偶尔把 size 写成字符串，那不该成为绕过这道闸的路。
    {"size": "10000"},
])
def test_oversized_hit_window_rejected(dsl):
    with pytest.raises(ValueError, match="RST_MAX_QUERY_SIZE"):
        validate_dsl(dsl)


def test_size_cap_is_configurable(monkeypatch):
    monkeypatch.setenv("RST_MAX_QUERY_SIZE", "50")
    with pytest.raises(ValueError, match="RST_MAX_QUERY_SIZE"):
        validate_dsl({"size": 51})
    validate_dsl({"size": 50})


def test_no_size_is_fine():
    """不写 size 就是 ES 默认的 10，没有什么要拦的。"""
    validate_dsl({"query": {"match_all": {}}})


# ---------------------------------------------------------------- 聚合桶数

def test_small_aggregation_passes():
    validate_dsl({"aggs": {"a": {"terms": {"field": "x", "size": 10}}}})


def test_single_huge_terms_rejected():
    with pytest.raises(ValueError, match="RST_MAX_AGG_BUCKETS"):
        validate_dsl({"aggs": {"a": {"terms": {"field": "x", "size": 50000}}}})


def test_nested_terms_multiply():
    """两个 1000 单看都不吓人，嵌起来是一百万个桶 —— 这条才是真正的成本洞。"""
    dsl = {
        "aggs": {
            "outer": {
                "terms": {"field": "host", "size": 1000},
                "aggs": {"inner": {"terms": {"field": "user", "size": 1000}}},
            }
        }
    }
    with pytest.raises(ValueError, match="1000000"):
        validate_dsl(dsl)


def test_sibling_aggregations_add_not_multiply():
    """同级是相加：两个 4000 是 8000，还在 10000 之内，不该被拦。"""
    validate_dsl({
        "aggs": {
            "a": {"terms": {"field": "x", "size": 4000}},
            "b": {"terms": {"field": "y", "size": 4000}},
        }
    })


def test_terms_without_size_counts_as_es_default():
    """terms 不写 size 时 ES 默认给 10。按 1 算的话，嵌套深了就会漏过去。"""
    dsl = {"aggs": {"a": {"terms": {"field": "x"}}}}
    validate_dsl(dsl)  # 10 个桶，当然过

    # 三层不写 size = 10×10×10 = 1000，仍在上限内；把上限压到 100 就该拦。
    deep = {
        "aggs": {"a": {"terms": {"field": "x"}, "aggs": {
            "b": {"terms": {"field": "y"}, "aggs": {
                "c": {"terms": {"field": "z"}}}}}}}
    }
    validate_dsl(deep)


def test_bucket_cap_is_configurable(monkeypatch):
    monkeypatch.setenv("RST_MAX_AGG_BUCKETS", "100")
    with pytest.raises(ValueError, match="RST_MAX_AGG_BUCKETS"):
        validate_dsl({"aggs": {"a": {"terms": {"field": "x", "size": 101}}}})
    validate_dsl({"aggs": {"a": {"terms": {"field": "x", "size": 100}}}})


def test_aggregations_long_form_is_also_counted():
    """ES 两个键都认（`aggs` / `aggregations`），只看一个等于留了条后门。"""
    with pytest.raises(ValueError, match="RST_MAX_AGG_BUCKETS"):
        validate_dsl({"aggregations": {"a": {"terms": {"field": "x", "size": 50000}}}})


def test_bad_env_value_falls_back_to_default(monkeypatch):
    """环境变量写坏了不该变成「没有上限」。"""
    monkeypatch.setenv("RST_MAX_QUERY_SIZE", "not-a-number")
    with pytest.raises(ValueError, match="RST_MAX_QUERY_SIZE"):
        validate_dsl({"size": 10000})

    monkeypatch.setenv("RST_MAX_QUERY_SIZE", "0")
    with pytest.raises(ValueError, match="RST_MAX_QUERY_SIZE"):
        validate_dsl({"size": 10000})
