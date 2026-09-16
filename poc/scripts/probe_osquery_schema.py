#!/usr/bin/env python3
"""osquery 结果索引字段探针 —— 基线巡检模块的前置。

判定引擎要从 ``logs-osquery_manager.result-*`` 里，对「某台主机 + 某条规则」
取最新 osquery 结果。但不同 Elastic / Fleet / Osquery Manager 版本下，三件事
的字段名会有差异，判定引擎的取值逻辑完全依赖它们：

  1. **query 身份字段**：一条 doc 是「哪条 osquery 查询」的结果 —— 判定引擎
     靠它把结果行对应到规则（关联键假设：Pack query 名 == rule_id）。
     候选：osquery.pack_name / osquery.action / query / labels.* / data_stream.dataset ...
  2. **主机标识字段**：host.name vs host.hostname vs agent.id vs agent.name。
  3. **结果列前缀**：osquery 的结果列在 ES 里挂在哪个前缀下（多为 ``osquery.*``）。

用法（在能连到客户 / 测试 ES 的机器上跑一次）：

    cd poc
    # 复用与 gateway 相同的 ES 连接环境变量
    export ES_URL=https://es:9200 ES_USER=... ES_PASSWORD=...
    python -m scripts.probe_osquery_schema
    # 可选：换索引模式 / 只看某台主机 / 调样本数
    python -m scripts.probe_osquery_schema --index "logs-osquery_manager.result-*" --size 5

脚本**只读**，不写任何东西。产出：
  - 终端打印：mapping 扁平字段表 + 样本文档 + 三项字段的启发式猜测。
  - 文件：``poc/scripts/osquery_probe_output.json`` —— 把它整份贴回来即可校准
    ``baseline/result_reader.py`` 里的字段常量。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# 复用 gateway 的 ES 客户端（认证 / 证书 / 超时逻辑一致），避免另起连接实现。
_POC = Path(__file__).resolve().parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.es_client import close_es, execute_search, friendly_es_error, get_mapping  # noqa: E402

DEFAULT_INDEX = "logs-osquery_manager.result-*"
OUTPUT_PATH = Path(__file__).resolve().parent / "osquery_probe_output.json"

# 三项未知字段的候选名 —— 探针据此在真实 mapping 里做启发式匹配。
QUERY_ID_CANDIDATES = (
    "osquery.pack_name", "osquery.name", "osquery.action", "action",
    "query", "labels.query_name", "data_stream.dataset", "event.dataset",
)
HOST_CANDIDATES = (
    "host.name", "host.hostname", "agent.id", "agent.name", "hostIdentifier",
)
RESULT_COL_PREFIXES = ("osquery.", "osquery_result.", "columns.")


def _flatten_mapping(props: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """把 ES mapping 的 properties 树扁平成 {字段路径: 类型}。"""
    out: dict[str, str] = {}
    for name, spec in (props or {}).items():
        path = f"{prefix}{name}"
        if not isinstance(spec, dict):
            continue
        if "properties" in spec:
            out.update(_flatten_mapping(spec["properties"], f"{path}."))
        else:
            out[path] = spec.get("type", "?")
        # 子字段（如 text 的 .keyword）
        for sub in (spec.get("fields") or {}):
            out[f"{path}.{sub}"] = (spec["fields"][sub] or {}).get("type", "?")
    return out


def _flatten_source(src: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """把一份 _source 扁平成 {路径: 值}，便于人眼看真实取值。"""
    out: dict[str, Any] = {}
    for k, v in (src or {}).items():
        path = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten_source(v, f"{path}."))
        else:
            out[path] = v
    return out


def _guess(fields: dict[str, str], candidates) -> list[str]:
    """按候选顺序，返回 mapping 里真实存在的字段。"""
    return [c for c in candidates if c in fields]


def _guess_result_cols(fields: dict[str, str]) -> dict[str, list[str]]:
    by_prefix: dict[str, list[str]] = {}
    for f in fields:
        for p in RESULT_COL_PREFIXES:
            if f.startswith(p):
                by_prefix.setdefault(p, []).append(f)
    return by_prefix


async def _run(index: str, size: int, host: str | None) -> dict[str, Any]:
    # 1) mapping —— 允许索引尚未创建 / 无权限时优雅降级。
    mapping_fields: dict[str, str] = {}
    mapping_error: str | None = None
    try:
        raw = await get_mapping(index)
        # get_mapping 对通配符会返回 {具体索引名: {mappings: {...}}}，逐个并集。
        for _idx, body in (raw or {}).items():
            props = ((body or {}).get("mappings") or {}).get("properties") or {}
            mapping_fields.update(_flatten_mapping(props))
    except Exception as e:  # noqa: BLE001
        _, mapping_error = friendly_es_error(e)

    # 2) 最新样本文档。
    sample_sources: list[dict[str, Any]] = []
    search_error: str | None = None
    dsl: dict[str, Any] = {
        "size": max(1, min(size, 20)),
        "sort": [{"@timestamp": {"order": "desc"}}],
    }
    if host:
        # 主机字段名未知 —— 用 multi_match 兜住常见候选。
        dsl["query"] = {"multi_match": {"query": host, "fields": list(HOST_CANDIDATES)}}
    try:
        resp = await execute_search(index, dsl)
        hits = ((resp or {}).get("hits") or {}).get("hits") or []
        sample_sources = [h.get("_source") or {} for h in hits]
    except Exception as e:  # noqa: BLE001
        _, search_error = friendly_es_error(e)

    flat_sample = _flatten_source(sample_sources[0]) if sample_sources else {}

    return {
        "index_pattern": index,
        "mapping_error": mapping_error,
        "search_error": search_error,
        "field_count": len(mapping_fields),
        "mapping_fields": dict(sorted(mapping_fields.items())),
        "sample_count": len(sample_sources),
        "sample_source_flat": dict(sorted(flat_sample.items())),
        "guesses": {
            "query_identity_field": _guess(mapping_fields, QUERY_ID_CANDIDATES),
            "host_field": _guess(mapping_fields, HOST_CANDIDATES),
            "result_columns_by_prefix": _guess_result_cols(mapping_fields),
        },
    }


def _print_report(r: dict[str, Any]) -> None:
    print("\n================ osquery 结果索引探针 ================")
    print(f"索引模式        : {r['index_pattern']}")
    print(f"mapping 字段数  : {r['field_count']}" + (f"  (错误: {r['mapping_error']})" if r["mapping_error"] else ""))
    print(f"样本文档数      : {r['sample_count']}" + (f"  (错误: {r['search_error']})" if r["search_error"] else ""))

    g = r["guesses"]
    print("\n--- 三项关键字段启发式猜测 ---")
    print(f"1) query 身份字段候选(命中): {g['query_identity_field'] or '⚠️ 未命中，请人工看下面字段表'}")
    print(f"2) 主机标识字段候选(命中)  : {g['host_field'] or '⚠️ 未命中'}")
    cols = g["result_columns_by_prefix"]
    if cols:
        for pfx, fs in cols.items():
            print(f"3) 结果列前缀 '{pfx}' : {len(fs)} 个字段，例如 {fs[:8]}")
    else:
        print("3) 结果列前缀            : ⚠️ 未命中常见前缀，请人工看字段表")

    if r["sample_source_flat"]:
        print("\n--- 样本文档(扁平，前 40 字段) ---")
        for i, (k, v) in enumerate(r["sample_source_flat"].items()):
            if i >= 40:
                print("  ... (更多见 JSON 输出文件)")
                break
            print(f"  {k} = {str(v)[:100]}")

    print(f"\n完整结果已写入: {OUTPUT_PATH}")
    print("把该 JSON 整份贴回，我据此校准 baseline/result_reader.py 的字段常量。")
    print("=====================================================\n")


async def _amain(index: str, size: int, host: str | None) -> int:
    try:
        report = await _run(index, size, host)
    finally:
        await close_es()
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_report(report)
    # 有可用样本或 mapping 即算成功；两者皆空则非 0，方便脚本化判断。
    return 0 if (report["field_count"] or report["sample_count"]) else 2


def main() -> None:
    ap = argparse.ArgumentParser(description="探测 osquery 结果索引字段结构（只读）")
    ap.add_argument("--index", default=DEFAULT_INDEX, help=f"索引模式，默认 {DEFAULT_INDEX}")
    ap.add_argument("--size", type=int, default=3, help="取最新样本文档数（1-20，默认 3）")
    ap.add_argument("--host", default=None, help="可选：只看某台主机（模糊匹配常见主机字段）")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_amain(args.index, args.size, args.host)))


if __name__ == "__main__":
    main()
