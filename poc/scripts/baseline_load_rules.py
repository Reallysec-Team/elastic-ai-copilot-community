#!/usr/bin/env python3
"""把 Phase1 规则库（18 条）导入 baseline-rules 索引（幂等，doc id=rule_id）。

规则源文件纳入仓库：backend/baseline/data/rules_phase1.json（客户环境无桌面文件）。
每条补 enabled=true、created_at/updated_at、空 remediation_command 占位。

用法:
    cd poc
    python -m scripts.baseline_load_rules
    python -m scripts.baseline_load_rules --file 自定义规则.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_POC = Path(__file__).resolve().parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.baseline import store  # noqa: E402
from backend.es_client import get_es, close_es  # noqa: E402

DEFAULT_RULES = _POC / "backend" / "baseline" / "data" / "rules_phase1.json"


def _to_doc(rule: dict[str, Any], now: str) -> dict[str, Any]:
    collect = rule.get("collect") or {}
    judge = rule.get("judge") or {}
    return {
        "rule_id": rule["rule_id"],
        "title": rule.get("title", ""),
        "category": rule.get("category", ""),
        "platform": rule.get("platform", "linux"),
        "standard_refs": rule.get("standard_refs") or [],
        "severity": rule.get("severity", "medium"),
        "depends_on": rule.get("depends_on"),
        "collect": {"type": collect.get("type", "osquery"), "query": collect.get("query", ""),
                    "query_name": collect.get("query_name") or rule["rule_id"]},
        "judge": {
            "operator": judge.get("operator", ""),
            "field": judge.get("field"),
            "expected": judge.get("expected"),
            "on_missing": judge.get("on_missing", "error"),
        },
        "remediation_template": rule.get("remediation_template", ""),
        "remediation_command": rule.get("remediation_command"),  # Phase1 = None
        "enabled": rule.get("enabled", True),
        "created_at": now,
        "updated_at": now,
    }


async def _run(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = data.get("rules") if isinstance(data, dict) else data
    if not rules:
        print(f"[error] {path} 无 rules")
        return 2
    now = datetime.now(timezone.utc).isoformat()
    es = get_es()
    ops: list[dict[str, Any]] = []
    for r in rules:
        ops.append({"index": {"_index": store.RULES_INDEX, "_id": r["rule_id"]}})
        ops.append(_to_doc(r, now))
    try:
        resp = await es.bulk(operations=ops, refresh=True)
    finally:
        await close_es()
    errs = [i for i in resp.body.get("items", []) if (i.get("index") or {}).get("error")]
    print(f"完成：导入 {len(rules)} 条规则到 {store.RULES_INDEX}" + (f"，{len(errs)} 条失败" if errs else "，全部成功"))
    if errs:
        print("首个错误:", errs[0]["index"]["error"])
        return 1
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="导入 Phase1 基线规则")
    ap.add_argument("--file", default=str(DEFAULT_RULES), help="规则 JSON 路径")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_run(Path(args.file))))


if __name__ == "__main__":
    main()
