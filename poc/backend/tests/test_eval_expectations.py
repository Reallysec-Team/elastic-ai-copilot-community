"""The eval's structural bar — what separates "it ran" from "it answered".

Every DSL literal below is a real (abbreviated) generation from eval/last_run.json.
"""
import pytest

from eval.expectations import agg_fields, agg_types, check, referenced_fields


def _result(hits: int = 10, aggs: dict | None = None) -> dict:
    out = {"hits": {"total": {"value": hits, "relation": "eq"}}}
    if aggs:
        out["aggregations"] = aggs
    return out


# ── extraction ───────────────────────────────────────────────────────────────

def test_finds_fields_named_in_query_clauses():
    dsl = {"query": {"bool": {"filter": [
        {"range": {"@timestamp": {"gte": "now/d"}}},
        {"terms": {"response": ["500", "503"]}},
    ]}}}
    assert referenced_fields(dsl) == {"@timestamp", "response"}


def test_keyword_subfield_is_the_same_field():
    dsl = {"aggs": {"by_url": {"terms": {"field": "url.keyword"}}}}
    assert agg_fields(dsl) == {"url"}
    assert referenced_fields(dsl) == {"url"}


def test_finds_the_sort_field_so_top_n_by_sort_counts():
    """`Top 10 流量最大的请求` is as correctly answered by a sort as by an agg."""
    dsl = {"size": 10, "sort": [{"bytes": {"order": "desc"}}]}
    assert "bytes" in referenced_fields(dsl)


def test_finds_nested_agg_types_and_fields():
    dsl = {"aggs": {"by_url": {
        "terms": {"field": "url.keyword", "size": 5},
        "aggs": {"ips": {"cardinality": {"field": "clientip"}}},
    }}}
    assert agg_types(dsl) == {"terms", "cardinality"}
    assert agg_fields(dsl) == {"url", "clientip"}


def test_a_value_that_merely_contains_a_field_name_is_not_a_reference():
    """Substring matching over the serialized DSL would call this a hit."""
    dsl = {"query": {"match": {"message": "url response bytes"}}}
    assert referenced_fields(dsl) == {"message"}


# ── the bar itself ───────────────────────────────────────────────────────────

def test_a_correct_answer_passes():
    dsl = {"size": 0,
           "query": {"range": {"@timestamp": {"gte": "now-7d"}}},
           "aggs": {"daily": {"date_histogram": {"field": "@timestamp", "calendar_interval": "day"}}}}
    expect = {"fields": ["@timestamp"], "agg_types": ["date_histogram"],
              "agg_fields": ["@timestamp"], "min_hits": 1}
    assert check(dsl, _result(hits=42), expect) == []


def test_match_all_executes_but_answers_nothing():
    """The exact hole in the old bar: this scored a full pass."""
    problems = check({"query": {"match_all": {}}}, _result(hits=300),
                     {"fields": ["response"], "agg_types": ["date_histogram"]})
    assert len(problems) == 2
    assert any("response" in p for p in problems)
    assert any("date_histogram" in p for p in problems)


def test_a_window_that_slid_off_the_data_is_caught():
    """`今天到现在多少个请求` against a dataset seeded yesterday."""
    dsl = {"query": {"range": {"@timestamp": {"gte": "now/d"}}}}
    problems = check(dsl, _result(hits=0), {"fields": ["@timestamp"], "min_hits": 1})
    assert problems == ["hits 0 < min_hits 1"]


def test_a_filter_that_never_got_written_is_caught():
    dsl = {"query": {"exists": {"field": "extension"}}}
    problems = check(dsl, _result(hits=300), {"fields": ["extension"], "max_hits": 299})
    assert problems == ["hits 300 > max_hits 299"]


def test_either_of_two_defensible_fields_satisfies_the_case():
    expect = {"fields": [["url", "request"]]}
    assert check({"query": {"prefix": {"request": "/api/"}}}, _result(), expect) == []
    assert check({"query": {"prefix": {"url": "/api/"}}}, _result(), expect) == []
    assert check({"query": {"match_all": {}}}, _result(), expect) == ["missing field: url | request"]


def test_a_refusal_fails_a_case_that_expects_an_answer():
    assert check(None, _result(), {"fields": ["@timestamp"]}) == ["refused, but the case expects an answer"]


def test_a_case_with_no_expectations_is_never_failed():
    """Old cases keep behaving exactly as before until someone writes an expect:."""
    assert check({"query": {"match_all": {}}}, _result(hits=0), None) == []
    assert check(None, _result(), {}) == []


@pytest.mark.parametrize("hits", [0, 1, 300])
def test_hit_bands_are_optional(hits):
    assert check({"query": {"match_all": {}}}, _result(hits=hits), {"agg_types": []}) == []
