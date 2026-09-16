"""判据 operator —— 纯函数，判定引擎的核心。

输入:
  judge : dict（或经 schema.Judge.as_dict()）—— {operator, field?, expected?, on_missing?}
  rows  : list[dict] —— 某主机某规则的 osquery 最新结果行（每行 = 列名→值）

输出: verdict 字符串（schema.VERDICT_*）。纯函数、无副作用、确定性 —— 同输入必同输出，
便于合规报告审计与复现（与 gateway 的确定性加固一致）。
"""
from __future__ import annotations

from typing import Any

from .schema import (
    ON_MISSING_ALLOWED,
    OP_EQUALS,
    OP_EXPECT_EMPTY,
    OP_EXPECT_NONEMPTY,
    OP_GTE,
    OP_LTE,
    OP_MANUAL,
    OP_NOT_EQUALS,
    VERDICT_ERROR,
    VERDICT_FAIL,
    VERDICT_MANUAL,
    VERDICT_PASS,
)


def evaluate(judge: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """按 operator 比对，返回 verdict。"""
    op = (judge or {}).get("operator")
    if not op:
        return VERDICT_ERROR

    rows = rows or []

    if op == OP_MANUAL:
        return VERDICT_MANUAL
    if op == OP_EXPECT_EMPTY:
        return VERDICT_PASS if len(rows) == 0 else VERDICT_FAIL
    if op == OP_EXPECT_NONEMPTY:
        return VERDICT_PASS if len(rows) >= 1 else VERDICT_FAIL
    if op in (OP_EQUALS, OP_NOT_EQUALS, OP_GTE, OP_LTE):
        return _evaluate_field_op(op, judge, rows)

    return VERDICT_ERROR


def _on_missing(judge: dict[str, Any]) -> str:
    v = (judge or {}).get("on_missing") or VERDICT_ERROR
    return v if v in ON_MISSING_ALLOWED else VERDICT_ERROR


def _first_value(judge: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[bool, Any]:
    """取第一行的 judge.field 值。equals 系语义针对单值查询（system_controls /
    selinux_settings 等），取首行即可。返回 (found, value)。"""
    field = (judge or {}).get("field")
    if not field or not rows:
        return False, None
    row = rows[0]
    if field not in row:
        return False, None
    return True, row[field]


def _evaluate_field_op(op: str, judge: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    found, value = _first_value(judge, rows)
    if not found:
        # 没有可比对的值（无行 / 行里没这个字段）→ 用 on_missing 兜底。
        return _on_missing(judge)

    expected = (judge or {}).get("expected")

    if op == OP_EQUALS:
        return VERDICT_PASS if str(value) == str(expected) else VERDICT_FAIL
    if op == OP_NOT_EQUALS:
        return VERDICT_PASS if str(value) != str(expected) else VERDICT_FAIL

    # gte / lte 需数值比较 —— 任一侧非数值 = error（判据/数据坏了，别静默当 fail）。
    try:
        lhs = float(str(value))
        rhs = float(str(expected))
    except (TypeError, ValueError):
        return VERDICT_ERROR
    if op == OP_GTE:
        return VERDICT_PASS if lhs >= rhs else VERDICT_FAIL
    return VERDICT_PASS if lhs <= rhs else VERDICT_FAIL  # OP_LTE


def summarize_actual(judge: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """把"实际观测"压成一句写进 baseline-results.actual，供报告展示。

    - empty/nonempty/manual: 报命中行数
    - equals 系: 报 field=值（取不到报 <缺失>）
    """
    op = (judge or {}).get("operator")
    rows = rows or []
    if op in (OP_EQUALS, OP_NOT_EQUALS, OP_GTE, OP_LTE):
        field = (judge or {}).get("field") or "?"
        found, value = _first_value(judge, rows)
        return f"{field}={value}" if found else f"{field}=<缺失>"
    return f"{len(rows)} 行"
