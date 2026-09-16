"""Named, read-only probes against the customer's Elasticsearch cluster.

Design constraint, not an oversight: this module exposes NO generic
`call(method, path)` escape hatch. The `_search` query surface guards itself
with `validate_dsl` / `index_whitelist` / `mask_doc`, but none of those apply
to cluster-admin APIs (`_cluster/health`, `_cat/shards`, `_nodes/stats`, ...) —
they were built to validate a DSL query body, not a management endpoint. A
generic proxy here would silently inherit zero of that protection and let a
future caller construct an arbitrary admin request. Instead every function
below hits exactly one hardcoded, read-only API via the elasticsearch-py
named client methods (`es.cluster.health()`, not `es.perform_request(...)`).
The function signature list IS the whitelist — there is nothing to smuggle a
path into.

Every function returns `(data, error)` and never raises. A customer's ES
account commonly lacks `monitor` or `manage_ilm` privileges; treating that as
a normal, reportable outcome (not a 500) is the whole point of `checks.py`
being able to degrade one check to UNKNOWN without losing the rest.
"""

from __future__ import annotations

import logging

from elasticsearch import (
    AuthenticationException,
    AuthorizationException,
    BadRequestError,
    ConnectionError as ESConnectionError,
    ConnectionTimeout,
    NotFoundError,
)

from ..es_client import get_es

logger = logging.getLogger("rst.platform_ops")


def _friendly_error(e: Exception) -> str:
    """Normalize a raw ES exception into a Chinese, human-actionable message.

    Deliberately not `es_client.friendly_es_error` — that one returns an HTTP
    status for the query API's error responses, a different contract than the
    plain string a probe needs here.
    """
    if isinstance(e, ConnectionTimeout):
        return "查询超时，集群可能负载较高"
    if isinstance(e, ESConnectionError):
        return "无法连接 Elasticsearch"
    if isinstance(e, AuthenticationException):
        return "认证失败：请检查 ES 账号配置"
    if isinstance(e, AuthorizationException):
        return "权限不足：当前 ES 账号缺少所需权限"
    if isinstance(e, NotFoundError):
        return "对应索引/资源不存在"
    text = str(e).lower()
    if "security_exception" in text or "unauthorized" in text or "403" in text:
        return "权限不足：当前 ES 账号缺少所需权限"
    return f"探测失败：{str(e)[:200]}"


async def cluster_health() -> tuple[dict | None, str | None]:
    try:
        es = get_es()
        res = await es.cluster.health()
        return dict(res), None
    except Exception as e:
        logger.warning("probe_cluster_health_failed", extra={"error": str(e)})
        return None, _friendly_error(e)


async def cat_shards() -> tuple[list | None, str | None]:
    try:
        es = get_es()
        res = await es.cat.shards(format="json")
        return list(res), None
    except Exception as e:
        logger.warning("probe_cat_shards_failed", extra={"error": str(e)})
        return None, _friendly_error(e)


async def allocation_explain() -> tuple[dict | None, str | None]:
    try:
        es = get_es()
        res = await es.cluster.allocation_explain()
        return dict(res), None
    except BadRequestError as e:
        # ES answers 400 when there is no unassigned shard for it to explain —
        # that is the healthy case, not a failure. Only surface an error if the
        # 400 is about something else.
        text = str(e).lower()
        if "unable to find any unassigned shards" in text or "no shard was specified" in text:
            return None, None
        logger.warning("probe_allocation_explain_failed", extra={"error": str(e)})
        return None, _friendly_error(e)
    except Exception as e:
        logger.warning("probe_allocation_explain_failed", extra={"error": str(e)})
        return None, _friendly_error(e)


async def nodes_thread_pool_stats() -> tuple[dict | None, str | None]:
    try:
        es = get_es()
        res = await es.nodes.stats(metric="thread_pool")
        return dict(res), None
    except Exception as e:
        logger.warning("probe_thread_pool_stats_failed", extra={"error": str(e)})
        return None, _friendly_error(e)


async def cat_allocation() -> tuple[list | None, str | None]:
    try:
        es = get_es()
        res = await es.cat.allocation(format="json")
        return list(res), None
    except Exception as e:
        logger.warning("probe_cat_allocation_failed", extra={"error": str(e)})
        return None, _friendly_error(e)


async def index_settings_blocks() -> tuple[dict | None, str | None]:
    try:
        es = get_es()
        res = await es.indices.get_settings(
            index="_all", name="index.blocks.read_only_allow_delete"
        )
        return dict(res), None
    except NotFoundError:
        # No index has the setting set — that's the common/healthy case.
        return {}, None
    except Exception as e:
        logger.warning("probe_index_settings_blocks_failed", extra={"error": str(e)})
        return None, _friendly_error(e)


async def ilm_explain() -> tuple[dict | None, str | None]:
    try:
        es = get_es()
        res = await es.ilm.explain_lifecycle(index="_all")
        return dict(res), None
    except Exception as e:
        logger.warning("probe_ilm_explain_failed", extra={"error": str(e)})
        return None, _friendly_error(e)


async def data_streams() -> tuple[list | None, str | None]:
    try:
        es = get_es()
        res = await es.indices.get_data_stream()
        return list(res.get("data_streams", [])), None
    except Exception as e:
        logger.warning("probe_data_streams_failed", extra={"error": str(e)})
        return None, _friendly_error(e)


async def time_baseline(index: str, host_field: str = "host.name") -> tuple[dict | None, str | None]:
    """一次聚合拿全「这个索引的时间对不对得上」需要的三个信号。

    分开三件事，因为它们的现象一样（查不到数据）而修法完全不同：

      max/min(@timestamp)   —— 比网关的 now **领先** = 采集端把本地时间当 UTC 写了，
                               或者机器时钟快了；**落后**很多 = 采集断了或索引陈旧
      按主机的 max          —— 只有几台偏 = 那几台没配 NTP，不是全局时区问题
      ingested - @timestamp —— 采集延迟。它不是错误，但「最近 5 分钟查不到」要靠
                               它来解释，否则用户会去查一个不存在的故障

    `event.ingested` 不是每个索引都有（要 ingest pipeline 写），没有就跳过那一项。
    """
    try:
        es = get_es()
        res = await es.search(
            index=index,
            size=0,
            aggs={
                "newest": {"max": {"field": "@timestamp"}},
                "oldest": {"min": {"field": "@timestamp"}},
                "by_host": {
                    "terms": {"field": host_field, "size": 20},
                    "aggs": {"newest": {"max": {"field": "@timestamp"}}},
                },
                "lag": {
                    "percentiles": {
                        "script": {
                            # 毫秒差。没有 event.ingested 的文档跳过 —— 返回 null
                            # 会让整个 percentiles 变成 null，那就什么都说不了。
                            "source": (
                                "if (!doc.containsKey('event.ingested') || doc['event.ingested'].empty) "
                                "{ return null; } "
                                "return doc['event.ingested'].value.toInstant().toEpochMilli() "
                                "- doc['@timestamp'].value.toInstant().toEpochMilli();"
                            ),
                        },
                        "percents": [50, 95],
                    }
                },
            },
        )
        aggs = res.get("aggregations", {})
        hosts = [
            {"host": b.get("key"), "newest": (b.get("newest") or {}).get("value_as_string")}
            for b in (aggs.get("by_host") or {}).get("buckets", [])
        ]
        return {
            "newest": (aggs.get("newest") or {}).get("value_as_string"),
            "oldest": (aggs.get("oldest") or {}).get("value_as_string"),
            "hosts": hosts,
            "lag_ms": (aggs.get("lag") or {}).get("values") or {},
        }, None
    except Exception as e:
        logger.warning("probe_time_baseline_failed", extra={"index": index, "error": str(e)})
        return None, _friendly_error(e)


async def last_doc_time(index: str) -> tuple[str | None, str | None]:
    try:
        es = get_es()
        res = await es.search(
            index=index,
            size=0,
            aggs={"m": {"max": {"field": "@timestamp"}}},
        )
        value = res.get("aggregations", {}).get("m", {}).get("value_as_string")
        return value, None
    except Exception as e:
        logger.warning("probe_last_doc_time_failed", extra={"index": index, "error": str(e)})
        return None, _friendly_error(e)
