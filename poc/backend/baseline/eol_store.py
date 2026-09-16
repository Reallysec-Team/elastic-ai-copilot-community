"""eol-catalog 索引读写（离线 EOL 判定的本地数据源）。

只用 ES（依赖最小）。判定期只读本地 catalog，绝不触外网 endoflife API；
外网拉取隔离在 scripts/eol_sync.py。索引名可经 env 覆盖，便于客户环境隔离。
"""
from __future__ import annotations

import logging
import os
from typing import Any

from ..es_client import get_es, execute_search
from .eol_catalog import doc_id

logger = logging.getLogger("rst.baseline.eol_store")

EOL_CATALOG_INDEX = os.environ.get("RST_BASELINE_EOL_INDEX", "").strip() or "eol-catalog"


async def lookup(product: str, cycle: str) -> dict[str, Any] | None:
    """查某产品某 cycle 的 EOL 记录。命中返回 _source，否则 None。"""
    dsl = {
        "size": 1,
        "query": {"bool": {"filter": [
            {"term": {"product": product}},
            {"term": {"cycle": cycle}},
        ]}},
    }
    resp = await execute_search(EOL_CATALOG_INDEX, dsl)
    hits = ((resp or {}).get("hits") or {}).get("hits") or []
    return (hits[0].get("_source") if hits else None)


async def bulk_upsert(docs: list[dict[str, Any]]) -> int:
    """批量 upsert catalog 记录。文档 id = product:cycle，幂等。返回写入条数。

    eol 为 None 时剔除该字段（date 类型不吃 null），避免 strict mapping 报错。
    """
    if not docs:
        return 0
    es = get_es()
    ops: list[dict[str, Any]] = []
    for d in docs:
        body = {k: v for k, v in d.items() if v is not None}
        ops.append({"index": {"_index": EOL_CATALOG_INDEX, "_id": doc_id(d)}})
        ops.append(body)
    resp = await es.bulk(operations=ops, refresh="wait_for")
    if resp.body.get("errors"):
        logger.warning("eol_catalog_upsert_partial_errors")
    return len(docs)


async def count() -> int:
    """catalog 当前记录数（供同步脚本报告 / 离线判空）。"""
    dsl = {"size": 0, "track_total_hits": True, "query": {"match_all": {}}}
    try:
        resp = await execute_search(EOL_CATALOG_INDEX, dsl)
    except Exception:  # noqa: BLE001
        return 0
    total = ((resp or {}).get("hits") or {}).get("total") or {}
    return int(total.get("value", 0)) if isinstance(total, dict) else int(total or 0)
