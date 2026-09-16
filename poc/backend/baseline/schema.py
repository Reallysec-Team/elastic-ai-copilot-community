"""基线巡检的领域类型与常量（不可变）。

规则库 schema 见桌面 baseline-rules-phase1.json；ES 三索引 mapping 见
baseline-index-mapping-and-dataflow.md。这里只放判定引擎需要的最小类型 +
枚举常量，避免全程用魔法字符串。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---- verdict 枚举（写入 baseline-results.verdict，keyword）----
VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_ERROR = "error"
VERDICT_MANUAL = "manual_review"
# stale：取到的 osquery 数据超出新鲜度窗口（或主机整体失联）。既不是 pass 也不是
# fail —— 我们对这台主机的当前状态没有证据。计分时与 error 同样不进分母。
# 只落 baseline-results（verdict 是 keyword，无需改 mapping）；batch 汇总里并入
# error 计数，避免给 dynamic:strict 的 baseline-runs 加字段而逼客户重跑建索引脚本。
VERDICT_STALE = "stale"
VERDICTS = frozenset({VERDICT_PASS, VERDICT_FAIL, VERDICT_ERROR, VERDICT_MANUAL, VERDICT_STALE})

# ---- operator 枚举（judge.operator）----
OP_EXPECT_EMPTY = "expect_empty"
OP_EXPECT_NONEMPTY = "expect_nonempty"
OP_EQUALS = "equals"
OP_NOT_EQUALS = "not_equals"
OP_GTE = "gte"
OP_LTE = "lte"
OP_MANUAL = "manual_review"
# eol：OS 版本 EOL 自动判定。语义需外部查 eol-catalog（非纯函数），
# 由 engine 单开分支调 baseline/eol.py，不塞进纯函数 operators（保持其纯净）。
OP_EOL = "eol"
OPERATORS = frozenset(
    {OP_EXPECT_EMPTY, OP_EXPECT_NONEMPTY, OP_EQUALS, OP_NOT_EQUALS, OP_GTE, OP_LTE, OP_MANUAL, OP_EOL}
)

# on_missing 只允许这几种落点（equals/gte/lte/not_equals 取不到值时的兜底 verdict）。
ON_MISSING_ALLOWED = frozenset({VERDICT_PASS, VERDICT_FAIL, VERDICT_ERROR})


@dataclass(frozen=True)
class Judge:
    """判据。operator 决定语义；field/expected 仅 equals 系用；on_missing 兜底。"""
    operator: str
    field: str | None = None
    expected: str | None = None
    on_missing: str = VERDICT_ERROR

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Judge":
        on_missing = str(d.get("on_missing") or VERDICT_ERROR)
        if on_missing not in ON_MISSING_ALLOWED:
            on_missing = VERDICT_ERROR
        return Judge(
            operator=str(d.get("operator") or ""),
            field=(str(d["field"]) if d.get("field") is not None else None),
            expected=(str(d["expected"]) if d.get("expected") is not None else None),
            on_missing=on_missing,
        )

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"operator": self.operator, "on_missing": self.on_missing}
        if self.field is not None:
            out["field"] = self.field
        if self.expected is not None:
            out["expected"] = self.expected
        return out


@dataclass(frozen=True)
class Rule:
    """一条基线规则（对应 baseline-rules 一个 doc）。"""
    rule_id: str
    title: str
    category: str
    platform: str
    severity: str
    judge: Judge
    collect_query: str
    query_name: str = ""       # osquery Pack 里的 query 名（关联键）；默认 = rule_id
    standard_refs: tuple[str, ...] = ()
    remediation_template: str = ""
    depends_on: str | None = None
    enabled: bool = True

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Rule":
        refs = d.get("standard_refs") or []
        if isinstance(refs, str):
            refs = [refs]
        collect = d.get("collect") or {}
        return Rule(
            rule_id=str(d["rule_id"]),
            title=str(d.get("title") or ""),
            category=str(d.get("category") or ""),
            platform=str(d.get("platform") or ""),
            severity=str(d.get("severity") or "medium"),
            judge=Judge.from_dict(d.get("judge") or {}),
            collect_query=str(collect.get("query") or ""),
            query_name=str(collect.get("query_name") or d["rule_id"]),
            standard_refs=tuple(str(r) for r in refs),
            remediation_template=str(d.get("remediation_template") or ""),
            depends_on=(str(d["depends_on"]) if d.get("depends_on") else None),
            enabled=bool(d.get("enabled", True)),
        )


@dataclass(frozen=True)
class Result:
    """一条判定结果（对应 baseline-results 一个 doc）。"""
    run_id: str
    rule_id: str
    title: str
    category: str
    severity: str
    host: str
    verdict: str
    actual: str
    expected: str
    checked_at: str
    standard_refs: tuple[str, ...] = ()
    agent_id: str | None = None
    evidence: str = ""
    remediation: str = ""

    def as_doc(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "rule_id": self.rule_id,
            "title": self.title,
            "category": self.category,
            "severity": self.severity,
            "host": self.host,
            "agent_id": self.agent_id,
            "verdict": self.verdict,
            "actual": self.actual,
            "expected": self.expected,
            "standard_refs": list(self.standard_refs),
            "evidence": self.evidence,
            "remediation": self.remediation,
            "checked_at": self.checked_at,
        }
