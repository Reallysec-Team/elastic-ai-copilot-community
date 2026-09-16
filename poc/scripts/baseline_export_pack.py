#!/usr/bin/env python3
"""导出 osquery Pack（方案 C）供客户导入 Fleet Osquery Manager。

默认离线：从仓库内规则源文件 backend/baseline/data/rules_phase1.json 生成，无需 ES。
也可 --from-es 从 baseline-rules 索引拉当前启用规则生成（规则被扩充/改过后用这个）。

    cd poc
    python -m scripts.baseline_export_pack                       # 离线，从规则源文件
    python -m scripts.baseline_export_pack --interval 3600
    ES_URL=... python -m scripts.baseline_export_pack --from-es  # 从 ES 现有规则

产物：backend/baseline/data/osquery_pack_phase1.json —— 交给客户在
Kibana → Osquery → Packs 导入。query 名 = rule_id，判定关联对齐 by construction。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

_POC = Path(__file__).resolve().parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.baseline import pack  # noqa: E402

SRC_RULES = _POC / "backend" / "baseline" / "data" / "rules_phase1.json"
OUT_PATH = _POC / "backend" / "baseline" / "data" / "osquery_pack_phase1.json"


def _rules_from_file(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("rules") if isinstance(data, dict) else data


async def _rules_from_es() -> list[dict[str, Any]]:
    from backend.baseline import store
    from backend.es_client import close_es
    try:
        rules = await store.load_enabled_rules()
    finally:
        await close_es()
    # store 返回 Rule 对象 —— 转回 dict 供 build_pack 统一处理。
    return [{"rule_id": r.rule_id, "title": r.title, "platform": r.platform,
             "collect": {"query": r.collect_query, "query_name": r.query_name},
             "judge": r.judge.as_dict()} for r in rules]


async def _run(from_es: bool, interval: int, out: Path) -> int:
    rules = await _rules_from_es() if from_es else _rules_from_file(SRC_RULES)
    p = pack.build_pack(rules, interval=interval)
    out.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] 导出 {len(p['queries'])} 条查询到 {out}")
    print("客户在 Kibana → Osquery → Packs 导入即可（query 名 = rule_id）。")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="导出 osquery Pack（方案 C）")
    ap.add_argument("--from-es", action="store_true", help="从 baseline-rules 索引拉规则（默认离线读源文件）")
    ap.add_argument("--interval", type=int, default=pack.DEFAULT_INTERVAL, help="查询间隔秒（默认 3600）")
    ap.add_argument("--out", default=str(OUT_PATH), help="输出路径")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_run(args.from_es, args.interval, Path(args.out))))


if __name__ == "__main__":
    main()
