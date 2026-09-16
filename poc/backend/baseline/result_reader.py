"""从 osquery 结果索引读取「某主机某规则」的最新结果行。

- 字段名走 field_detect 运行时自检（部署后自主适配，卡点1）。
- 检索 DSL 走确定性 query_builder（卡点2，不走 LLM）。
- 一次 osquery 运行可产多行、每行一 doc；取回一窗口后按 @timestamp 选最新一轮全部行。
"""
from __future__ import annotations

import logging
import os
from typing import Any

from ..es_client import execute_search, get_mapping
from . import field_detect, query_builder
from .field_detect import FieldMap

logger = logging.getLogger("rst.baseline.result_reader")

DEFAULT_RESULT_INDEX = "logs-osquery_manager.result-*"

_field_map_cache: FieldMap | None = None


def result_index() -> str:
    """客户 osquery 结果索引（读）。

    正名是 `RST_BASELINE_OSQUERY_INDEX`。原来叫 `RST_BASELINE_RESULT_INDEX`，
    跟 `store.py` 的 `RST_BASELINE_RESULTS_INDEX`（我们自己写判定结果的那个）
    只差一个 s，而两者方向相反：一个是读客户的原始数据，一个是写我们的结论。
    客户做索引隔离时设错一个，症状是「基线页空白 / 全判 stale」，看代码才分得
    出来。旧名继续认，但会记一行 warning。
    """
    v = os.environ.get("RST_BASELINE_OSQUERY_INDEX", "").strip()
    if v:
        return v
    legacy = os.environ.get("RST_BASELINE_RESULT_INDEX", "").strip()
    if legacy:
        logger.warning(
            "RST_BASELINE_RESULT_INDEX 已改名为 RST_BASELINE_OSQUERY_INDEX（"
            "旧名跟 RST_BASELINE_RESULTS_INDEX 差一个 s，指的是相反的两件事）",
        )
        return legacy
    return DEFAULT_RESULT_INDEX


def roster_days() -> int:
    """主机枚举窗口（天）。<= 0 = 不限时间。误配回落默认值。"""
    try:
        v = int(os.environ.get("RST_BASELINE_HOST_ROSTER_DAYS", "").strip())
    except (TypeError, ValueError):
        return query_builder.DEFAULT_HOST_ROSTER_DAYS
    return v


def reset_cache() -> None:
    """清字段自检缓存（测试 / 客户换 ELK 后重新自检）。"""
    global _field_map_cache
    _field_map_cache = None


async def get_field_map() -> FieldMap:
    """自检并缓存 FieldMap。首次拉 mapping 探测，之后走缓存。"""
    global _field_map_cache
    if _field_map_cache is not None:
        return _field_map_cache
    fields: dict[str, str] = {}
    try:
        raw = await get_mapping(result_index())
        for _idx, body in (raw or {}).items():
            props = ((body or {}).get("mappings") or {}).get("properties") or {}
            fields.update(field_detect.flatten_mapping(props))
    except Exception as e:  # noqa: BLE001
        logger.warning("baseline_field_map_mapping_failed", extra={"error": str(e)})
    fm = field_detect.detect_from_fields(fields)
    logger.info("baseline_field_map_resolved", extra=fm.as_dict())
    _field_map_cache = fm
    return fm


def _row_ts(h: dict[str, Any]) -> Any:
    return field_detect.get_by_path(h.get("_source") or {}, query_builder.TIME_FIELD)


def select_latest_rows(hits: list[dict[str, Any]], fm: FieldMap) -> list[dict[str, Any]]:
    """从时间倒序的 hits 里，挑出最新一轮（同 @timestamp）的所有结果行，抽出列。"""
    if not hits:
        return []
    newest = _row_ts(hits[0])
    out: list[dict[str, Any]] = []
    for h in hits:
        if _row_ts(h) != newest:
            break  # 已按时间倒序，遇到旧一轮即停
        out.append(field_detect.extract_columns(h.get("_source") or {}, fm))
    return out


async def fetch_latest(host: str, rule_id: str) -> tuple[list[dict[str, Any]], Any]:
    """取某主机某规则的最新结果行 + 这批行的采集时间（@timestamp）。

    返回 (rows, collected_at)。无任何结果时 collected_at 为 None —— 注意这不等于
    "主机失联"：expect_empty 规则本来就可能一行都不产。两者的区分见 host_last_seen。
    """
    fm = await get_field_map()
    dsl = query_builder.build_latest_query(host, rule_id, fm)
    resp = await execute_search(result_index(), dsl)
    hits = ((resp or {}).get("hits") or {}).get("hits") or []
    if not hits:
        return [], None
    return select_latest_rows(hits, fm), _row_ts(hits[0])


async def fetch_rows(host: str, rule_id: str) -> list[dict[str, Any]]:
    """取某主机某规则的最新结果行（列名→值）。"""
    rows, _ = await fetch_latest(host, rule_id)
    return rows


async def host_last_seen(host: str) -> Any:
    """某主机最近一次上报任何 osquery 数据的时间；从没上报过 → None。"""
    fm = await get_field_map()
    dsl = query_builder.build_host_last_seen_query(host, fm)
    resp = await execute_search(result_index(), dsl)
    agg = ((resp or {}).get("aggregations") or {}).get("last_seen") or {}
    # date 字段的 max 聚合：value 是 epoch_millis，value_as_string 才是 ISO。
    return agg.get("value_as_string") or None


async def list_hosts() -> list[str]:
    """枚举上报过 osquery 的主机集合（限 roster 窗口，退役机器不再枚举）。"""
    fm = await get_field_map()
    dsl = query_builder.build_hosts_query(fm, roster_days=roster_days())
    resp = await execute_search(result_index(), dsl)
    buckets = (((resp or {}).get("aggregations") or {}).get("hosts") or {}).get("buckets") or []
    return [b["key"] for b in buckets if b.get("key")]
