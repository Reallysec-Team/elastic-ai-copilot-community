"""判定 operator 纯函数单测（TDD）。

operator 语义（见 baseline-rules-phase1.json 的 operator_semantics）:
  expect_empty    查询 0 行 = pass；≥1 行 = fail
  expect_nonempty 查询 ≥1 行 = pass；0 行 = fail
  equals          取 field 值 == expected = pass
  not_equals      取 field 值 != expected = pass
  gte             field 值 >= expected = pass
  lte             field 值 <= expected = pass
  manual_review   永远 manual_review（留人工）

on_missing: 需要取 field 值但没有行时（equals/not_equals/gte/lte），
用 judge.on_missing（pass/fail/error）兜底。
"""
from __future__ import annotations

import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))


from backend.baseline import operators  # noqa: E402
from backend.baseline.schema import (  # noqa: E402
    VERDICT_PASS,
    VERDICT_FAIL,
    VERDICT_ERROR,
    VERDICT_MANUAL,
)


# ---- expect_empty ----
def test_expect_empty_zero_rows_is_pass():
    assert operators.evaluate({"operator": "expect_empty"}, []) == VERDICT_PASS


def test_expect_empty_one_row_is_fail():
    assert operators.evaluate({"operator": "expect_empty"}, [{"username": "bad"}]) == VERDICT_FAIL


def test_expect_empty_many_rows_is_fail():
    rows = [{"u": "a"}, {"u": "b"}]
    assert operators.evaluate({"operator": "expect_empty"}, rows) == VERDICT_FAIL


# ---- expect_nonempty ----
def test_expect_nonempty_one_row_is_pass():
    assert operators.evaluate({"operator": "expect_nonempty"}, [{"chain": "INPUT"}]) == VERDICT_PASS


def test_expect_nonempty_zero_rows_is_fail():
    assert operators.evaluate({"operator": "expect_nonempty"}, []) == VERDICT_FAIL


# ---- equals ----
def test_equals_match_is_pass():
    judge = {"operator": "equals", "field": "current_value", "expected": "0", "on_missing": "fail"}
    assert operators.evaluate(judge, [{"current_value": "0"}]) == VERDICT_PASS


def test_equals_mismatch_is_fail():
    judge = {"operator": "equals", "field": "current_value", "expected": "0", "on_missing": "fail"}
    assert operators.evaluate(judge, [{"current_value": "1"}]) == VERDICT_FAIL


def test_equals_missing_row_uses_on_missing_fail():
    judge = {"operator": "equals", "field": "current_value", "expected": "0", "on_missing": "fail"}
    assert operators.evaluate(judge, []) == VERDICT_FAIL


def test_equals_missing_row_uses_on_missing_pass():
    judge = {"operator": "equals", "field": "mode", "expected": "enforcing", "on_missing": "pass"}
    assert operators.evaluate(judge, []) == VERDICT_PASS


def test_equals_field_absent_in_row_uses_on_missing():
    judge = {"operator": "equals", "field": "current_value", "expected": "0", "on_missing": "error"}
    assert operators.evaluate(judge, [{"other": "x"}]) == VERDICT_ERROR


# ---- not_equals ----
def test_not_equals_differs_is_pass():
    judge = {"operator": "not_equals", "field": "v", "expected": "0", "on_missing": "fail"}
    assert operators.evaluate(judge, [{"v": "1"}]) == VERDICT_PASS


def test_not_equals_same_is_fail():
    judge = {"operator": "not_equals", "field": "v", "expected": "0", "on_missing": "fail"}
    assert operators.evaluate(judge, [{"v": "0"}]) == VERDICT_FAIL


# ---- gte / lte ----
def test_gte_pass_and_fail():
    judge = {"operator": "gte", "field": "n", "expected": "90", "on_missing": "fail"}
    assert operators.evaluate(judge, [{"n": "90"}]) == VERDICT_PASS
    assert operators.evaluate(judge, [{"n": "120"}]) == VERDICT_PASS
    assert operators.evaluate(judge, [{"n": "30"}]) == VERDICT_FAIL


def test_lte_pass_and_fail():
    judge = {"operator": "lte", "field": "n", "expected": "90", "on_missing": "fail"}
    assert operators.evaluate(judge, [{"n": "30"}]) == VERDICT_PASS
    assert operators.evaluate(judge, [{"n": "90"}]) == VERDICT_PASS
    assert operators.evaluate(judge, [{"n": "120"}]) == VERDICT_FAIL


def test_gte_non_numeric_value_is_error():
    judge = {"operator": "gte", "field": "n", "expected": "90", "on_missing": "fail"}
    assert operators.evaluate(judge, [{"n": "not-a-number"}]) == VERDICT_ERROR


# ---- manual_review ----
def test_manual_review_always_manual():
    assert operators.evaluate({"operator": "manual_review"}, []) == VERDICT_MANUAL
    assert operators.evaluate({"operator": "manual_review"}, [{"x": 1}]) == VERDICT_MANUAL


# ---- unknown / malformed ----
def test_unknown_operator_is_error():
    assert operators.evaluate({"operator": "bogus"}, []) == VERDICT_ERROR


def test_missing_operator_is_error():
    assert operators.evaluate({}, []) == VERDICT_ERROR


def test_actual_summary_reports_matched_row_count():
    # 判定引擎要把"实际观测"写进结果，供报告展示。
    assert operators.summarize_actual({"operator": "expect_empty"}, []) == "0 行"
    assert operators.summarize_actual({"operator": "expect_empty"}, [{"a": 1}, {"a": 2}]) == "2 行"


def test_actual_summary_reports_field_value():
    judge = {"operator": "equals", "field": "current_value", "expected": "0"}
    assert operators.summarize_actual(judge, [{"current_value": "1"}]) == "current_value=1"
