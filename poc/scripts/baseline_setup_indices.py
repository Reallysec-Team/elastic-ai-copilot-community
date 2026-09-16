#!/usr/bin/env python3
"""建 baseline-rules / baseline-results / baseline-runs 三索引（幂等）。

用法（连到目标 ES 的环境变量同 gateway）:
    cd poc
    python -m scripts.baseline_setup_indices          # 已存在则跳过
    python -m scripts.baseline_setup_indices --force  # 删除重建（危险，会清数据）
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.baseline import eol_store, indices, store  # noqa: E402
from backend.es_client import get_es, close_es  # noqa: E402


async def _run(force: bool) -> int:
    es = get_es()
    specs = indices.index_specs(store.RULES_INDEX, store.RESULTS_INDEX, store.RUNS_INDEX,
                                eol_store.EOL_CATALOG_INDEX)
    created = 0
    try:
        for name, body in specs:
            exists = await es.indices.exists(index=name)
            if exists:
                if force:
                    await es.indices.delete(index=name)
                    print(f"[force] 删除旧索引 {name}")
                else:
                    # 幂等升级：对已存在索引做 additive put_mapping，补齐新版新增字段
                    # （如 baseline-rules 的 source / collect.query_name）。加字段在
                    # dynamic:strict 索引上是允许的；字段类型冲突才会报错。
                    mappings = body.get("mappings") or {}
                    if mappings.get("properties"):
                        try:
                            await es.indices.put_mapping(
                                index=name, properties=mappings["properties"])
                            print(f"[update] {name} mapping 已补齐新增字段")
                        except Exception as e:  # noqa: BLE001
                            print(f"[warn] {name} mapping 更新失败（可能有字段类型冲突）：{e}")
                    else:
                        print(f"[skip] {name} 已存在")
                    continue
            await es.indices.create(index=name, body=body)
            print(f"[ok] 建索引 {name}")
            created += 1
    finally:
        await close_es()
    print(f"完成：新建 {created} 个索引。")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="建基线三索引（幂等）")
    ap.add_argument("--force", action="store_true", help="删除并重建（会清空数据）")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_run(args.force)))


if __name__ == "__main__":
    main()
