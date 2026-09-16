"""确定性 ES 检索 DSL builder（卡点2：判定取数不走 LLM）。

判定引擎对每台主机、每条规则取 osquery 最新结果。查询形状固定 —— 纯函数拼装，
同输入必得同 DSL，可复现、可审计、零 token 成本，且与 gateway 的确定性加固一致。

关联键假设：Pack query 名 == rule_id，落在 FieldMap.query_field。
"""
from __future__ import annotations

from typing import Any

from .field_detect import FieldMap

TIME_FIELD = "@timestamp"
DEFAULT_ROW_WINDOW = 500   # 一次 osquery 运行可产多行，取足够窗口覆盖最新一轮
DEFAULT_HOST_LIMIT = 1000
# 主机花名册窗口：多久没上报过任何数据的主机不再枚举（退役机器不该永远排队）。
# 这不是新鲜度判据 —— 判据在 engine，窗口内但陈旧的主机要被判 stale 而不是消失。
DEFAULT_HOST_ROSTER_DAYS = 30


def build_latest_query(host: str, rule_id: str, fm: FieldMap, size: int = DEFAULT_ROW_WINDOW) -> dict[str, Any]:
    """取「主机 host + 规则 rule_id」的结果行，按时间倒序、限窗。

    result_reader 再从中挑出最新一轮（同 @timestamp）的所有行喂给 operators。

    刻意不加时间下界：operators.evaluate 对 expect_empty 系规则「0 行 = 通过」，
    在 DSL 里把陈旧行过滤掉，会让半年没上报的主机在"无高危端口/无越权账户"这类
    规则上全线判 pass —— 比按陈旧数据判定更糟。新鲜度由 engine 拿实际
    @timestamp 比对 max-age 后判 stale，这样还能报出"最后采集于 X"。
    """
    return {
        "size": size,
        "query": {
            "bool": {
                "filter": [
                    {"term": {fm.host_field: host}},
                    {"term": {fm.query_field: rule_id}},
                ]
            }
        },
        "sort": [{TIME_FIELD: {"order": "desc"}}],
    }


def build_hosts_query(fm: FieldMap, size: int = DEFAULT_HOST_LIMIT,
                      roster_days: int = DEFAULT_HOST_ROSTER_DAYS) -> dict[str, Any]:
    """枚举结果索引里上报过 osquery 的主机集合（terms 聚合）。判定引擎据此定目标主机。

    roster_days <= 0 关闭时间窗（枚举索引里的全部历史主机）。
    """
    dsl: dict[str, Any] = {
        "size": 0,
        "aggs": {"hosts": {"terms": {"field": fm.host_field, "size": size}}},
    }
    if roster_days > 0:
        dsl["query"] = {"bool": {"filter": [
            {"range": {TIME_FIELD: {"gte": f"now-{roster_days}d"}}}
        ]}}
    return dsl


def build_host_last_seen_query(host: str, fm: FieldMap) -> dict[str, Any]:
    """取某主机最近一次上报任何 osquery 数据的时间（max 聚合）。

    区分两种「没数据」：主机整体失联（→ 全部规则 stale），与主机在报但某条规则
    本轮没产行（expect_empty 的合法空结果，仍交给 operators）。
    """
    return {
        "size": 0,
        "query": {"bool": {"filter": [{"term": {fm.host_field: host}}]}},
        "aggs": {"last_seen": {"max": {"field": TIME_FIELD}}},
    }
