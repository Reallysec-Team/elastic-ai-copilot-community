"""界面时间范围落到 DSL 上：剥离、注入、以及「什么都不该发生」的情形。

这层是纯函数，因为它改的是要发给 ES 的查询 —— 改错的结果不是报错，是一份看上去
正常、其实统计的是另一段时间的结果。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import time_window as tw  # noqa: E402

SINCE = "2026-09-05T21:47:00Z"
UNTIL = "2026-09-05T22:15:00Z"


# ---- 时间字段的解析 --------------------------------------------------------


def test_prefers_at_timestamp():
    m = {"properties": {"@timestamp": {"type": "date"}, "event": {
        "properties": {"created": {"type": "date"}}}}}
    assert tw.resolve_time_field(m) == "@timestamp"


def test_unwraps_the_raw_es_shape():
    """ES 的 get_mapping 返回 {索引名: {mappings: {properties: …}}}，
    调用方不该为了这层包装再写一次拆包。"""
    m = {"logs-2026": {"mappings": {"properties": {"@timestamp": {"type": "date"}}}}}
    assert tw.resolve_time_field(m) == "@timestamp"


def test_falls_back_to_the_only_date_field():
    m = {"properties": {"evt_time": {"type": "date"}, "msg": {"type": "text"}}}
    assert tw.resolve_time_field(m) == "evt_time"


def test_prefers_a_top_level_field_over_a_nested_one():
    m = {"properties": {
        "ingested_at": {"type": "date"},
        "file": {"properties": {"mtime": {"type": "date"}}},
    }}
    assert tw.resolve_time_field(m) == "ingested_at"


def test_no_date_field_returns_none():
    """返回 None 的场合调用方必须把「范围未生效」说出来 —— 静默失效意味着用户
    以为筛了，其实没有。"""
    assert tw.resolve_time_field({"properties": {"msg": {"type": "text"}}}) is None
    assert tw.resolve_time_field({}) is None
    assert tw.resolve_time_field(None) is None


# ---- 默认不改变任何东西 ----------------------------------------------------


def test_no_window_is_a_no_op():
    dsl = {"query": {"match_all": {}}, "size": 10}
    out, mode = tw.apply_window(dsl, "@timestamp", None, None)
    assert out == dsl and mode == tw.MODE_ADDED


# ---- 注入 -----------------------------------------------------------------


def test_wraps_a_bare_query_in_a_bool_filter():
    out, mode = tw.apply_window({"query": {"match": {"msg": "failed"}}},
                                "@timestamp", SINCE, UNTIL)
    b = out["query"]["bool"]
    # 原子句进 must 而不是 filter：它可能是要打分的。
    assert b["must"] == [{"match": {"msg": "failed"}}]
    assert b["filter"] == [{"range": {"@timestamp": {"gte": SINCE, "lte": UNTIL}}}]
    assert mode == tw.MODE_ADDED


def test_appends_to_an_existing_bool_filter():
    dsl = {"query": {"bool": {"filter": [{"term": {"host.name": "web-01"}}]}}}
    out, _ = tw.apply_window(dsl, "@timestamp", SINCE)
    flt = out["query"]["bool"]["filter"]
    assert {"term": {"host.name": "web-01"}} in flt
    assert {"range": {"@timestamp": {"gte": SINCE}}} in flt


def test_query_less_aggregation_gets_a_window_too():
    """只有聚合、没有 query 的统计查询是最常见的一类 —— 时间窗对它同样要生效。"""
    dsl = {"size": 0, "aggs": {"by_rule": {"terms": {"field": "rule.name"}}}}
    out, _ = tw.apply_window(dsl, "@timestamp", SINCE, UNTIL)
    assert out["query"]["bool"]["filter"][0]["range"]["@timestamp"]["gte"] == SINCE
    assert out["aggs"] == dsl["aggs"]


# ---- 覆盖 -----------------------------------------------------------------


def test_replaces_the_models_relative_window():
    """模型写了 now-30m，选择器选的是昨晚 —— AND 起来结果必空，然后客户去排查一个
    不存在的数据问题。选择器是唯一的时间来源。"""
    dsl = {"query": {"bool": {"filter": [
        {"range": {"@timestamp": {"gte": "now-30m"}}},
        {"term": {"event.outcome": "failure"}},
    ]}}}
    out, mode = tw.apply_window(dsl, "@timestamp", SINCE, UNTIL)
    flt = out["query"]["bool"]["filter"]
    assert mode == tw.MODE_REPLACED, "覆盖了就要告诉界面，界面要显示出来"
    assert {"term": {"event.outcome": "failure"}} in flt, "别的条件是用户真正问的东西"
    ranges = [c for c in flt if "range" in c]
    assert ranges == [{"range": {"@timestamp": {"gte": SINCE, "lte": UNTIL}}}]


def test_does_not_strip_ranges_inside_should():
    dsl = {"query": {"bool": {"must": [
        {"bool": {"should": [{"range": {"@timestamp": {"lt": "now-1d"}}}]}},
    ]}}}
    out, mode = tw.apply_window(dsl, "@timestamp", SINCE)
    # should 里的时间条件表达的是形状不是窗口 —— 保留它，只再 AND 一层。
    assert mode == tw.MODE_INTERSECTED
    assert "now-1d" in str(out)


def test_keeps_ranges_on_other_fields():
    """只剥时间字段。`bytes > 1000` 是用户问的条件，不是时间条件。"""
    dsl = {"query": {"bool": {"filter": [
        {"range": {"http.response.bytes": {"gt": 1000}}},
        {"range": {"@timestamp": {"gte": "now-1h"}}},
    ]}}}
    out, mode = tw.apply_window(dsl, "@timestamp", SINCE)
    flt = out["query"]["bool"]["filter"]
    assert {"range": {"http.response.bytes": {"gt": 1000}}} in flt
    assert mode == tw.MODE_REPLACED


def test_keeps_the_other_half_of_a_shared_range_clause():
    """一个 range 子句里同时写了时间和别的字段 —— 只拿走时间那半。"""
    dsl = {"query": {"bool": {"filter": [
        {"range": {"@timestamp": {"gte": "now-1h"}, "bytes": {"gt": 10}}},
    ]}}}
    out, mode = tw.apply_window(dsl, "@timestamp", SINCE)
    flt = out["query"]["bool"]["filter"]
    assert {"range": {"bytes": {"gt": 10}}} in flt
    assert mode == tw.MODE_REPLACED


def test_emptied_clause_leaves_no_illegal_leftover():
    """剥空的 `{"range": {}}` 留在 filter 数组里，ES 直接 400。"""
    dsl = {"query": {"bool": {"filter": [{"range": {"@timestamp": {"gte": "now-1h"}}}]}}}
    out, _ = tw.apply_window(dsl, "@timestamp", SINCE)
    assert {} not in out["query"]["bool"]["filter"]
    assert all(c != {"range": {}} for c in out["query"]["bool"]["filter"])


def test_is_idempotent():
    """generate 和 execute 两处都会套一次（前者让用户看见，后者是保证）——
    套两次不能出来两个时间窗。"""
    dsl = {"query": {"match_all": {}}}
    once, _ = tw.apply_window(dsl, "@timestamp", SINCE, UNTIL)
    twice, mode = tw.apply_window(once, "@timestamp", SINCE, UNTIL)
    assert twice == once
    assert mode == tw.MODE_REPLACED  # 第二次剥掉的是自己上一次写进去的


def test_input_is_not_mutated():
    dsl = {"query": {"bool": {"filter": [{"range": {"@timestamp": {"gte": "now-1h"}}}]}}}
    before = str(dsl)
    tw.apply_window(dsl, "@timestamp", SINCE)
    assert str(dsl) == before


# ---- 形状：不能替换的那些 ------------------------------------------------


def _daily_window_dsl():
    """提示词教模型的写法：「最近 3 天每天凌晨 00:00-06:00」= should 里三个 range
    加 minimum_should_match（prompts.py 里有原样的例子）。"""
    return {"query": {"bool": {"should": [
        {"range": {"@timestamp": {"gte": "now/d", "lt": "now/d+6h", "time_zone": "+08:00"}}},
        {"range": {"@timestamp": {"gte": "now-1d/d", "lt": "now-1d/d+6h", "time_zone": "+08:00"}}},
        {"range": {"@timestamp": {"gte": "now-2d/d", "lt": "now-2d/d+6h", "time_zone": "+08:00"}}},
    ], "minimum_should_match": 1}}, "size": 0}


def test_daily_window_shape_survives():
    """剥掉这三段会剩下 `should: []` 配 `minimum_should_match: 1` —— ES 一条都不
    匹配，界面上是一个没有任何提示的空结果。这是这条修复的全部理由。"""
    out, mode = tw.apply_window(_daily_window_dsl(), "@timestamp", SINCE, UNTIL)
    b = out["query"]["bool"]
    assert mode == tw.MODE_INTERSECTED
    assert len(b["should"]) == 3, "形状不能被剥掉"
    assert b["minimum_should_match"] == 1
    assert b["filter"] == [{"range": {"@timestamp": {"gte": SINCE, "lte": UNTIL}}}]


def test_must_not_time_range_is_not_stripped():
    """「排除维护窗口那两小时」—— 剥掉它等于把用户的排除条件删了。"""
    dsl = {"query": {"bool": {
        "must_not": [{"range": {"@timestamp": {"gte": "now-2h", "lt": "now-1h"}}}],
        "filter": [{"term": {"event.outcome": "failure"}}],
    }}}
    out, mode = tw.apply_window(dsl, "@timestamp", SINCE)
    assert mode == tw.MODE_INTERSECTED
    assert out["query"]["bool"]["must_not"] == dsl["query"]["bool"]["must_not"]


def test_two_top_level_ranges_are_intersected_not_replaced():
    """两段就已经不是「一个窗口」了 —— 谁替换谁说不清楚，只能相交。"""
    dsl = {"query": {"bool": {"filter": [
        {"range": {"@timestamp": {"gte": "now-1d"}}},
        {"range": {"@timestamp": {"lt": "now-1h"}}},
    ]}}}
    out, mode = tw.apply_window(dsl, "@timestamp", SINCE)
    assert mode == tw.MODE_INTERSECTED
    assert len([c for c in out["query"]["bool"]["filter"] if "range" in c]) == 3


def test_intersection_never_produces_an_empty_should():
    """这条守的是「不管什么形状，都不会出现 should:[] + mss:1」这个不变式。"""
    for dsl in (_daily_window_dsl(),
                {"query": {"bool": {"should": [{"range": {"@timestamp": {"gte": "now-1h"}}}],
                                    "minimum_should_match": 1}}}):
        out, _ = tw.apply_window(dsl, "@timestamp", SINCE, UNTIL)
        b = out["query"]["bool"]
        assert not (b.get("should") == [] and b.get("minimum_should_match"))


# ---- 谁说了算 --------------------------------------------------------------


def test_parse_time_intent_needs_explicit_and_since():
    """半截的声明不如不要 —— 判成没有就退回筛选器优先，也就是加这个字段之前的行为。"""
    from backend.llm import parse_time_intent as p

    assert p({}) is None
    assert p({"time_intent": {"explicit": False, "since": SINCE}}) is None
    assert p({"time_intent": {"explicit": True}}) is None            # 没有 since
    assert p({"time_intent": {"explicit": True, "text": "23号"}}) is None
    assert p({"time_intent": "23号"}) is None                        # 形状不对
    got = p({"time_intent": {"explicit": True, "text": "23号",
                             "since": SINCE, "until": UNTIL}})
    assert got == {"explicit": True, "text": "23号", "since": SINCE, "until": UNTIL}


def test_parse_time_intent_tolerates_a_missing_until():
    """「23号之后」这类只有下界的说法是合法的。"""
    from backend.llm import parse_time_intent as p

    got = p({"time_intent": {"explicit": True, "text": "23号以来", "since": SINCE}})
    assert got and got["since"] == SINCE and "until" not in got
