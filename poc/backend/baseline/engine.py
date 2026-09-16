"""判定引擎编排。

定时/手动触发 → 拉 enabled 规则 → 逐主机逐规则取 osquery 最新结果 → operators 判定
→ 写 baseline-results + baseline-runs（含评分）。

判定本身确定性（operators 纯函数 + query_builder 确定性 DSL）。remediation 取规则
静态模板；LLM 整改增强留作后续接缝（不破坏判定确定性）。
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Any

from . import eol, result_reader, store
from . import operators
from .schema import (
    OP_EOL,
    Result,
    Rule,
    VERDICT_ERROR,
    VERDICT_FAIL,
    VERDICT_MANUAL,
    VERDICT_PASS,
    VERDICT_STALE,
)

logger = logging.getLogger("rst.baseline.engine")

# 数据新鲜度窗口（小时）。超窗 → stale，不按陈旧数据判 pass/fail。
# 默认 48h = 允许漏一个采集周期（Fleet/Osquery Manager 的 pack interval 常见
# 3600s 或 86400s）。客户 pack 跑得比这慢，就把这个值调到 interval 的 2 倍以上。
# <= 0 关闭新鲜度判定（回到「按最后一次采集判定」的旧行为，不推荐）。
DEFAULT_MAX_AGE_HOURS = 48.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _max_age_hours() -> float:
    raw = os.environ.get("RST_BASELINE_MAX_AGE_HOURS", "").strip()
    if not raw:
        return DEFAULT_MAX_AGE_HOURS
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("baseline_max_age_invalid", extra={"value": raw})
        return DEFAULT_MAX_AGE_HOURS


def _parse_iso(v: Any) -> datetime | None:
    if not v:
        return None
    s = str(v).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _age_hours(collected: Any, now_iso: str) -> float | None:
    """采集时间距本轮判定的小时数。collected 不可解析 → None。"""
    a = _parse_iso(collected)
    if a is None:
        return None
    b = _parse_iso(now_iso) or datetime.now(timezone.utc)
    return (b - a).total_seconds() / 3600.0


def _stale_actual(what: str, collected: Any, age_hours: float | None) -> str:
    if not collected:
        return f"{what}数据过期：索引中查不到该主机的 osquery 上报"
    if age_hours is None:
        return f"{what}数据过期：最后采集于 {collected}（时间戳无法解析）"
    return f"{what}数据过期：最后采集于 {collected}，{age_hours / 24:.1f} 天前"


def _score(pass_n: int, fail_n: int) -> float | None:
    """合规评分 = pass / (pass+fail) × 100。error/manual_review 不计入分母
    （无法判定的项不该拉低或抬高达标率）。

    无可判项时返回 None（"未评估"），不是 100。返回 100 意味着"检查过，全部通过"，
    而 denom==0 的真实含义恰恰相反——一条规则都没评上。规则库为空（例如种子写入
    因 ES 写权限失败）或没有主机上报时都会走到这里，此时记分板显示"100 分 / 完全
    合规"，是对一台从未被检查过的机器给出的最危险的那种误导。"""
    denom = pass_n + fail_n
    if denom == 0:
        return None
    return round(pass_n / denom * 100, 1)


def _build_result(run_id: str, rule: Rule, host: str, verdict: str,
                  actual: str, checked_at: str) -> Result:
    # remediation 仅 fail/manual_review 带（pass 无需整改）。
    remediation = rule.remediation_template if verdict in (VERDICT_FAIL, VERDICT_MANUAL) else ""
    return Result(
        run_id=run_id,
        rule_id=rule.rule_id,
        title=rule.title,
        category=rule.category,
        severity=rule.severity,
        host=host,
        verdict=verdict,
        actual=actual,
        expected=(rule.judge.expected or ""),
        checked_at=checked_at,
        standard_refs=rule.standard_refs,
        remediation=remediation,
    )


def _derive_date(iso: str) -> date:
    """从 ISO 时间串取日期（EOL 比对用）。解析失败退当日。"""
    try:
        return date.fromisoformat(iso[:10])
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).date()


async def run_baseline(run_id: str, hosts: list[str] | None = None,
                       now_iso: str | None = None,
                       eval_date: date | None = None) -> dict[str, Any]:
    """跑一轮基线判定。now_iso / eval_date 可注入以保证可测/可复现。返回批次汇总。

    eval_date：EOL 判定的「当前日期」，缺省由 now_iso 派生（确定性）。
    """
    started = now_iso or _now_iso()
    eval_day = eval_date or _derive_date(started)
    explicit_hosts = hosts is not None
    rules = await store.load_enabled_rules()
    if hosts is None:
        hosts = await result_reader.list_hosts()

    counts = {VERDICT_PASS: 0, VERDICT_FAIL: 0, VERDICT_ERROR: 0,
              VERDICT_MANUAL: 0, VERDICT_STALE: 0}
    results: list[Result] = []
    max_age = _max_age_hours()

    for host in hosts:
        # 主机级新鲜度：整台失联时全部规则判 stale，且不必再逐规则取数。
        # 与规则级的区别：主机在报、但某条规则本轮没产行，是 expect_empty 的合法
        # 空结果，仍交给 operators —— 不能一律当过期。
        host_last_seen, host_stale = None, False
        if max_age > 0:
            try:
                host_last_seen = await result_reader.host_last_seen(host)
                host_age = _age_hours(host_last_seen, started)
                host_stale = host_last_seen is None or host_age is None or host_age > max_age
            except Exception as e:  # noqa: BLE001
                # 探测失败是 ES 故障，不是「主机失联」。保持原判定路径，让真正的
                # 取数失败以 error 呈现，而不是把一次 ES 抖动说成数据过期。
                logger.warning("baseline_host_last_seen_failed",
                               extra={"host": host, "error": str(e)})

        for rule in rules:
            if host_stale:
                verdict = VERDICT_STALE
                actual = _stale_actual("主机", host_last_seen,
                                       _age_hours(host_last_seen, started))
                counts[verdict] = counts.get(verdict, 0) + 1
                results.append(_build_result(run_id, rule, host, verdict, actual, started))
                continue
            judge = rule.judge.as_dict()
            try:
                # 按 query_name（默认 rule_id）取 osquery 结果 —— 关联键。
                rows, collected_at = await result_reader.fetch_latest(host, rule.query_name)
                age = _age_hours(collected_at, started)
                if max_age > 0 and collected_at is not None and (age is None or age > max_age):
                    # 主机在报，但这条规则的采集停了（pack 里被删/查询报错）。
                    verdict, actual = VERDICT_STALE, _stale_actual("该项", collected_at, age)
                elif judge.get("operator") == OP_EOL:
                    # EOL 需外查本地 eol-catalog + 注入当前日期，不塞进纯函数 operators。
                    verdict, actual = await eol.judge_eol(rows, today=eval_day)
                else:
                    verdict = operators.evaluate(judge, rows)
                    actual = operators.summarize_actual(judge, rows)
            except Exception as e:  # noqa: BLE001
                # 取数/判定异常 → error verdict，不中断整轮巡检。
                logger.warning("baseline_rule_eval_failed",
                               extra={"rule_id": rule.rule_id, "host": host, "error": str(e)})
                verdict, actual = VERDICT_ERROR, f"error: {str(e)[:120]}"
            counts[verdict] = counts.get(verdict, 0) + 1
            results.append(_build_result(run_id, rule, host, verdict, actual, started))

    await store.write_results(run_id, results)
    finished = now_iso or _now_iso()
    summary = {
        "run_id": run_id,
        "trigger": "manual" if explicit_hosts else "scheduled",
        "rule_count": len(rules),
        "host_count": len(hosts),
        "pass": counts[VERDICT_PASS],
        "fail": counts[VERDICT_FAIL],
        # stale 并入 error：baseline-runs 是 dynamic:strict，加一个计数字段会让老
        # 部署的 write_run 直接被 ES 拒写，除非客户先重跑 baseline_setup_indices。
        # 逐条结果里 verdict 仍是 stale，前端能分开显示。
        "error": counts[VERDICT_ERROR] + counts[VERDICT_STALE],
        "manual_review": counts[VERDICT_MANUAL],
        "score": _score(counts[VERDICT_PASS], counts[VERDICT_FAIL]),
        "started_at": started,
        "finished_at": finished,
    }
    await store.write_run(summary)
    logger.info("baseline_run_done", extra={**{k: summary[k] for k in
                ("run_id", "host_count", "rule_count", "pass", "fail", "score")},
                "stale": counts[VERDICT_STALE]})
    return summary
