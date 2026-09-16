"""baseline-rules / baseline-results / baseline-runs 三索引读写。

只用 ES（依赖最小，无新中间件）。索引名可经 env 覆盖，便于客户环境隔离。
"""
from __future__ import annotations

import logging
import os
from typing import Any

from ..es_client import get_es, execute_search
from .schema import Result, Rule

logger = logging.getLogger("rst.baseline.store")

RULES_INDEX = os.environ.get("RST_BASELINE_RULES_INDEX", "").strip() or "baseline-rules"
RESULTS_INDEX = os.environ.get("RST_BASELINE_RESULTS_INDEX", "").strip() or "baseline-results"
RUNS_INDEX = os.environ.get("RST_BASELINE_RUNS_INDEX", "").strip() or "baseline-runs"


# Shipped compliance pack. The rules travel inside the image; nothing used to
# put them INTO Elasticsearch — that was a manual `python -m
# scripts.baseline_load_rules` step, so on a fresh deployment the baseline page
# showed an empty rule library and looked broken. Seeded at startup instead.
_BUNDLED_RULES = os.path.join(os.path.dirname(__file__), "data", "rules_normal.json")


def rule_from_hit(hit: dict[str, Any]) -> Rule:
    return Rule.from_dict(hit.get("_source") or {})


async def seed_bundled_rules_if_empty(path: str | None = None) -> int:
    """Load the shipped compliance pack when the rule library is empty.

    Returns the number of rules written (0 = nothing to do).

    ONLY seeds an empty library. A customer who curated the pack — disabled
    rules, deleted the ones that don't apply, wrote their own — must not have
    it grow back on the next restart, so a library with any document in it is
    left completely alone. Best-effort throughout: a seeding failure logs and
    the gateway starts normally with an empty library, exactly as before.
    """
    import json
    from datetime import datetime, timezone

    src = path or _BUNDLED_RULES
    try:
        es = get_es()
        if await es.indices.exists(index=RULES_INDEX):
            cnt = (await es.count(index=RULES_INDEX)).body.get("count", 0)
            if cnt:
                return 0
        with open(src, encoding="utf-8") as fh:
            data = json.load(fh)
        rules = data.get("rules") if isinstance(data, dict) else data
        if not rules:
            logger.warning("baseline_seed_empty_source", extra={"path": src})
            return 0

        now = datetime.now(timezone.utc).isoformat()
        ops: list[dict[str, Any]] = []
        for r in rules:
            rid = r.get("rule_id")
            if not rid:
                continue
            collect = r.get("collect") or {}
            judge = r.get("judge") or {}
            ops.append({"index": {"_index": RULES_INDEX, "_id": rid}})
            ops.append({
                "rule_id": rid,
                "title": r.get("title", ""),
                "category": r.get("category", ""),
                "platform": r.get("platform", "linux"),
                "standard_refs": r.get("standard_refs") or [],
                "severity": r.get("severity", "medium"),
                "depends_on": r.get("depends_on"),
                "collect": {
                    "type": collect.get("type", "osquery"),
                    "query": collect.get("query", ""),
                    "query_name": collect.get("query_name") or rid,
                },
                "judge": {
                    "operator": judge.get("operator", ""),
                    "field": judge.get("field"),
                    "expected": judge.get("expected"),
                    "on_missing": judge.get("on_missing", "error"),
                },
                "remediation_template": r.get("remediation_template", ""),
                "remediation_command": r.get("remediation_command"),
                "enabled": r.get("enabled", True),
                "created_at": now,
                "updated_at": now,
            })
        if not ops:
            return 0
        resp = await es.bulk(operations=ops, refresh=True)
        errs = [i for i in resp.body.get("items", []) if (i.get("index") or {}).get("error")]
        n = len(ops) // 2 - len(errs)
        logger.info("baseline_rules_seeded", extra={"count": n, "errors": len(errs)})
        return n
    except Exception as e:  # noqa: BLE001 — never block startup
        logger.warning("baseline_seed_failed", extra={"error": str(e)})
        return 0


async def load_enabled_rules(platform: str | None = None) -> list[Rule]:
    """拉 enabled=true 的规则（可按平台过滤）。"""
    filters: list[dict[str, Any]] = [{"term": {"enabled": True}}]
    if platform:
        filters.append({"term": {"platform": platform}})
    dsl = {"size": 1000, "query": {"bool": {"filter": filters}}}
    resp = await execute_search(RULES_INDEX, dsl)
    hits = ((resp or {}).get("hits") or {}).get("hits") or []
    return [rule_from_hit(h) for h in hits]


def rule_to_doc(r: Rule) -> dict[str, Any]:
    """Serialize a Rule back to the baseline-rules doc shape (nested collect/judge)
    so it round-trips through Rule.from_dict. Tags source=custom for in-app authored
    rules (pack-loaded rules keep whatever source they were imported with)."""
    return {
        "rule_id": r.rule_id,
        "title": r.title,
        "category": r.category,
        "platform": r.platform,
        "severity": r.severity,
        "judge": r.judge.as_dict(),
        "collect": {"query": r.collect_query, "query_name": r.query_name},
        "standard_refs": list(r.standard_refs),
        "remediation_template": r.remediation_template,
        "depends_on": r.depends_on,
        "enabled": r.enabled,
        "source": "custom",
    }


async def list_all_rules(platform: str | None = None) -> list[dict[str, Any]]:
    """所有规则（含 disabled），供规则库浏览/编辑。返回原始 _source。"""
    filters: list[dict[str, Any]] = []
    if platform:
        filters.append({"term": {"platform": platform}})
    query = {"bool": {"filter": filters}} if filters else {"match_all": {}}
    dsl = {"size": 2000, "query": query}
    try:
        resp = await execute_search(RULES_INDEX, dsl)
    except Exception:  # noqa: BLE001 — index may not exist yet on a fresh install
        return []
    hits = ((resp or {}).get("hits") or {}).get("hits") or []
    rows = [h.get("_source") or {} for h in hits]
    rows.sort(key=lambda d: str(d.get("rule_id") or ""))
    return rows


async def list_runs(size: int = 50) -> list[dict[str, Any]]:
    """历史批次汇总（最近优先），供巡检历史/下钻。"""
    dsl = {"size": max(1, min(size, 500)), "query": {"match_all": {}},
           "sort": [{"finished_at": {"order": "desc"}}]}
    try:
        resp = await execute_search(RUNS_INDEX, dsl)
    except Exception:  # noqa: BLE001
        return []
    hits = ((resp or {}).get("hits") or {}).get("hits") or []
    return [h.get("_source") or {} for h in hits]


async def upsert_rule(r: Rule) -> None:
    """写入/更新一条规则（文档 id = rule_id，幂等）。引擎下一轮即读到。"""
    es = get_es()
    await es.index(index=RULES_INDEX, id=r.rule_id, document=rule_to_doc(r), refresh="wait_for")


async def delete_rule(rule_id: str) -> bool:
    """删除一条规则。返回是否删成功（不存在 → False）。"""
    es = get_es()
    try:
        await es.delete(index=RULES_INDEX, id=rule_id, refresh="wait_for")
        return True
    except Exception:  # noqa: BLE001 — 404 not-found or transport error
        return False


async def write_results(run_id: str, results: list[Result]) -> int:
    """批量写判定结果。文档 id = run_id:rule_id:host，幂等。返回写入条数。"""
    if not results:
        return 0
    es = get_es()
    ops: list[dict[str, Any]] = []
    for r in results:
        ops.append({"index": {"_index": RESULTS_INDEX, "_id": f"{run_id}:{r.rule_id}:{r.host}"}})
        ops.append(r.as_doc())
    # wait_for：跑完一轮后前端立即查结果，避免 refresh 时延导致"跑完却空表"。
    resp = await es.bulk(operations=ops, refresh="wait_for")
    if resp.body.get("errors"):
        logger.warning("baseline_write_results_partial_errors", extra={"run_id": run_id})
    return len(results)


async def write_run(summary: dict[str, Any]) -> None:
    """写批次汇总。文档 id = run_id，幂等。"""
    es = get_es()
    await es.index(index=RUNS_INDEX, id=summary["run_id"], document=summary, refresh="wait_for")


async def list_results(run_id: str | None = None, host: str | None = None,
                       verdict: str | None = None, size: int = 1000) -> list[dict[str, Any]]:
    """查判定结果（供前端结果页）。"""
    filters: list[dict[str, Any]] = []
    if run_id:
        filters.append({"term": {"run_id": run_id}})
    if host:
        filters.append({"term": {"host": host}})
    if verdict:
        filters.append({"term": {"verdict": verdict}})
    query = {"bool": {"filter": filters}} if filters else {"match_all": {}}
    dsl = {"size": max(1, min(size, 5000)), "query": query,
           "sort": [{"checked_at": {"order": "desc"}}]}
    resp = await execute_search(RESULTS_INDEX, dsl)
    hits = ((resp or {}).get("hits") or {}).get("hits") or []
    return [h.get("_source") or {} for h in hits]


async def latest_run() -> dict[str, Any] | None:
    """最近一次批次汇总（供前端评分卡）。"""
    dsl = {"size": 1, "query": {"match_all": {}}, "sort": [{"finished_at": {"order": "desc"}}]}
    try:
        resp = await execute_search(RUNS_INDEX, dsl)
    except Exception:  # noqa: BLE001
        return None
    hits = ((resp or {}).get("hits") or {}).get("hits") or []
    return (hits[0].get("_source") if hits else None)
