"""An unsorted LLM-authored DSL must come back newest-first.

Regression: `logs-system.security-default` is a data stream. Without a `sort`
ES merges hits in backing-index order (oldest generation first), so a `size: 10`
query over months of data returned ten documents from the oldest index and the
UI showed "newest log = May".
"""

from backend.validator import apply_default_sort

SORT = [{"@timestamp": {"order": "desc", "unmapped_type": "date"}}]


def test_unsorted_query_gets_newest_first():
    out = apply_default_sort({"size": 10, "query": {"match_all": {}}})
    assert out["sort"] == SORT


def test_caller_sort_is_never_overridden():
    dsl = {"size": 10, "sort": [{"event.created": "asc"}]}
    assert apply_default_sort(dsl)["sort"] == [{"event.created": "asc"}]


def test_aggregation_only_query_is_left_alone():
    dsl = {"size": 0, "aggs": {"users": {"terms": {"field": "user.name"}}}}
    assert "sort" not in apply_default_sort(dsl)


def test_input_is_not_mutated():
    dsl = {"size": 10}
    apply_default_sort(dsl)
    assert "sort" not in dsl


def test_non_dict_passes_through():
    assert apply_default_sort(None) is None
