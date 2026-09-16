"""Structural assertions over a generated DSL and the result it produced.

"Executes against ES without error" says nothing about whether the query
answered the question — a syntactically perfect `match_all` scores the same as
a correct `date_histogram`. These checks are the cheapest thing that separates
the two without pinning the DSL to one exact shape the model must reproduce
verbatim: there are several right ways to count 5xx per day, and all of them
mention `response`, bucket by date, and match fewer than every document.

A case declares only what it can declare honestly. Where two shapes are equally
correct (top-N by `sort` vs. by a `terms` agg) the case asserts less rather than
asserting the wrong one — a gate that fails on a correct answer is worse than a
loose one.

Expectation keys, all optional (see cases.yaml):

    fields:     each must be referenced somewhere in the DSL
    agg_types:  each must appear as an aggregation type
    agg_fields: each must be the target field of some aggregation
    min_hits:   hits.total.value floor  (catches a time window slid off the data)
    max_hits:   hits.total.value ceiling (catches a filter that never got written)

Every entry of the three list keys may itself be a list, meaning "any of these"
— `[[url, request]]` accepts either field, because both are defensible readings
of "首页访问数".
"""
from typing import Any, Iterator

# Query clauses whose body is keyed BY the field name.
_FIELD_KEYED_CLAUSES = {
    "range", "term", "terms", "match", "match_phrase", "match_phrase_prefix",
    "match_bool_prefix", "wildcard", "prefix", "regexp", "fuzzy", "terms_set",
}
# Keys inside an aggregation body that are not the aggregation's type.
_AGG_NON_TYPE = {"aggs", "aggregations", "meta"}


def _dicts(node: Any) -> Iterator[dict]:
    """Every dict in the tree, including the root."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _dicts(v)
    elif isinstance(node, list):
        for v in node:
            yield from _dicts(v)


def _agg_bodies(dsl: Any) -> Iterator[dict]:
    """Every aggregation definition — the dict holding `{"terms": {...}}`."""
    for d in _dicts(dsl):
        for container in ("aggs", "aggregations"):
            body = d.get(container)
            if isinstance(body, dict):
                for agg in body.values():
                    if isinstance(agg, dict):
                        yield agg


def _bare(field: str) -> str:
    """`geo.dest.keyword` and `geo.dest` are the same field for our purposes."""
    return field[: -len(".keyword")] if field.endswith(".keyword") else field


def agg_types(dsl: Any) -> set[str]:
    return {k for agg in _agg_bodies(dsl) for k in agg if k not in _AGG_NON_TYPE}


def agg_fields(dsl: Any) -> set[str]:
    out = set()
    for agg in _agg_bodies(dsl):
        for key, body in agg.items():
            if key in _AGG_NON_TYPE or not isinstance(body, dict):
                continue
            if isinstance(body.get("field"), str):
                out.add(_bare(body["field"]))
    return out


def referenced_fields(dsl: Any) -> set[str]:
    """Every field the DSL names — in a query clause, an agg, a sort or a script.

    Deliberately structural rather than a substring search over the serialized
    DSL: `"url"` appears inside plenty of values that have nothing to do with
    the field.
    """
    out: set[str] = set()
    for d in _dicts(dsl):
        for key, value in d.items():
            if key == "field" and isinstance(value, str):
                out.add(_bare(value))
            elif key in _FIELD_KEYED_CLAUSES and isinstance(value, dict):
                # `terms` is both a query clause keyed BY the field
                # ({"terms": {"response": [...]}}) and an aggregation naming it
                # ({"terms": {"field": "url"}}). Only the former keys by field.
                if "field" not in value:
                    out.update(_bare(k) for k in value if isinstance(k, str))
            elif key == "exists" and isinstance(value, dict):
                if isinstance(value.get("field"), str):
                    out.add(_bare(value["field"]))
            elif key == "sort":
                for entry in value if isinstance(value, list) else [value]:
                    if isinstance(entry, str):
                        out.add(_bare(entry))
                    elif isinstance(entry, dict):
                        out.update(_bare(k) for k in entry if isinstance(k, str))
    return out


def _missing(required: list, present: set[str]) -> list[str]:
    """Which requirements no present value satisfies. An entry that is itself a
    list is satisfied by any one of its alternatives."""
    gaps = []
    for req in required:
        options = req if isinstance(req, list) else [req]
        if not any(_bare(str(o)) in present for o in options):
            gaps.append(" | ".join(str(o) for o in options))
    return gaps


def check(dsl: Any, result: dict, expect: dict | None) -> list[str]:
    """Return one short string per unmet expectation. Empty list = case answered."""
    if not expect:
        return []
    if dsl is None:
        return ["refused, but the case expects an answer"]

    problems = []
    for label, required, present in (
        ("field", expect.get("fields") or [], referenced_fields(dsl)),
        ("agg type", expect.get("agg_types") or [], agg_types(dsl)),
        ("agg on field", expect.get("agg_fields") or [], agg_fields(dsl)),
    ):
        for gap in _missing(required, present):
            problems.append(f"missing {label}: {gap}")

    hits = (result.get("hits") or {}).get("total") or {}
    hits = hits.get("value") if isinstance(hits, dict) else hits
    if isinstance(hits, int):
        lo, hi = expect.get("min_hits"), expect.get("max_hits")
        if lo is not None and hits < lo:
            problems.append(f"hits {hits} < min_hits {lo}")
        if hi is not None and hits > hi:
            problems.append(f"hits {hits} > max_hits {hi}")
    return problems
