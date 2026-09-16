"""Validate an in-app authored baseline rule before it is written to ES.

Pure (no I/O) so it unit-tests without a cluster. Raises ApiError (which is a
ValueError) carrying an error code on the first problem; returns a validated Rule
otherwise. The engine will pick the rule up on its next run via
store.load_enabled_rules, so bad input here would drive real security verdicts —
validate strictly.
"""
from __future__ import annotations

import re
from typing import Any

from ..api_errors import ApiError
from .schema import (
    OP_EOL,
    OP_EQUALS,
    OP_EXPECT_EMPTY,
    OP_EXPECT_NONEMPTY,
    OP_GTE,
    OP_LTE,
    OP_MANUAL,
    OP_NOT_EQUALS,
    OPERATORS,
    Rule,
)

_RULE_ID_RE = re.compile(r"[A-Za-z0-9._-]{3,64}")
_SEVERITIES = frozenset({"low", "medium", "high", "critical"})
# operators that compare an osquery column to an expected value
_NEEDS_EXPECTED = frozenset({OP_EQUALS, OP_NOT_EQUALS, OP_GTE, OP_LTE})
# operators that read a specific column out of the osquery rows
_NEEDS_FIELD = frozenset(
    {OP_EQUALS, OP_NOT_EQUALS, OP_GTE, OP_LTE, OP_EXPECT_EMPTY, OP_EXPECT_NONEMPTY}
)


def validate_rule_payload(d: dict[str, Any]) -> Rule:
    if not isinstance(d, dict):
        raise ApiError("body_not_object")

    rid = str(d.get("rule_id") or "").strip()
    if not _RULE_ID_RE.fullmatch(rid):
        raise ApiError("rule_id_invalid")

    if not str(d.get("title") or "").strip():
        raise ApiError("rule_title_required")

    sev = str(d.get("severity") or "medium").strip().lower()
    if sev not in _SEVERITIES:
        raise ApiError("rule_severity_invalid", value=repr(sev), choices=sorted(_SEVERITIES))

    judge = d.get("judge")
    if not isinstance(judge, dict):
        raise ApiError("rule_judge_missing")
    op = str(judge.get("operator") or "").strip()
    if op not in OPERATORS:
        raise ApiError("rule_operator_invalid", value=repr(op), choices=sorted(OPERATORS))

    collect = d.get("collect")
    query = ""
    if isinstance(collect, dict):
        query = str(collect.get("query") or "").strip()
    # Every data-driven operator needs an osquery SQL to collect rows; only a pure
    # manual_review rule may omit it (a human dispositions it).
    if op != OP_MANUAL and not query:
        raise ApiError("rule_query_required")

    if op in _NEEDS_FIELD and not str(judge.get("field") or "").strip():
        raise ApiError("rule_needs_field", operator=op)
    if op in _NEEDS_EXPECTED and not str(judge.get("expected") or "").strip():
        raise ApiError("rule_needs_expected", operator=op)
    if op == OP_EOL and not query:
        raise ApiError("rule_eol_needs_query")

    # Final shaping + on_missing validation lives in the domain model.
    try:
        rule = Rule.from_dict({**d, "severity": sev})
    except Exception as e:  # noqa: BLE001
        raise ApiError("rule_shape_invalid", reason=e) from e
    return rule
