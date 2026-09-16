"""导入的资产表 / 身份表，只读的一面。

导入走 `csv_import`，解析走 `resolver` + `sources/csv_source`。这个模块两样都不碰：
它只回答界面上的两个问题 —— **我导进去了什么**，以及 **导进去的到底有没有用上**。

写在单独一个模块而不是塞进 resolver，是因为解析在请求路径上：那条路每加一个功能就
多一分把调查拖慢或拖挂的风险，而这两个查询是管理员偶尔打开一次的。共用的只有索引名
和归一化函数（`entity.normalize_*`）—— 匹配口径必须和解析时一致，否则覆盖率会说谎。
"""

from __future__ import annotations

import logging
from typing import Any

from .entity import normalize_host, normalize_ip, normalize_user
from .sources.csv_source import ASSETS_INDEX, IDENTITIES_INDEX

logger = logging.getLogger("rst.enrich.inventory")

KINDS = ("assets", "identities")

# 覆盖率抽样的告警条数上限。抽样而不是全量：这是一个「大概生效了没有」的指标，
# 为它扫全量告警不值得，而且告警索引可以很大。
_COVERAGE_SAMPLE = 500

# 列表页一次最多回多少行。
_MAX_LIMIT = 200


def _index(kind: str) -> str:
    return ASSETS_INDEX if kind == "assets" else IDENTITIES_INDEX


def _alerts_index() -> str:
    # 和 alerts.store 同一个来源，避免这里写死一个会漂的名字。
    from ..alerts import store as alert_store

    return alert_store._index()


async def list_entries(
    kind: str, q: str | None, limit: int, after: int, es
) -> dict[str, Any]:
    """一页已导入的行。`after` 是偏移量（这张表是人手维护的量级，不需要游标）。"""
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    limit = max(1, min(limit, _MAX_LIMIT))
    after = max(0, after)

    query: dict[str, Any] = {"match_all": {}}
    if q and q.strip():
        # 搜的是人会记得的那几列：名字、责任人、部门、类别，外加 join 键本身
        # （主机名 / IP / 用户名）—— 排障时手里往往就只有一个主机名。
        query = {
            "simple_query_string": {
                "query": q.strip(),
                "fields": [
                    "name", "owner", "department", "category",
                    "keys", "ip", "user_key",
                ],
                "default_operator": "and",
            }
        }

    body = {
        "query": query,
        # 名字排序要走 keyword 子字段：CSV 导入靠动态映射，name 是 text（分词过的），
        # 直接排会报 illegal_argument。
        "sort": [{"name.keyword": {"order": "asc", "unmapped_type": "keyword"}}],
        "from": after,
        "size": limit,
        "track_total_hits": True,
    }
    try:
        resp = await es.search(index=_index(kind), body=body)
    except Exception as e:  # noqa: BLE001
        # 索引还不存在（一次都没导过）也走这里 —— 那不是错误，是「还没有数据」。
        logger.debug("inventory list failed (%s): %s", kind, e)
        return {"total": 0, "rows": [], "next": None}

    res = getattr(resp, "body", resp)
    hits = (res.get("hits") or {}) if isinstance(res, dict) else {}
    total_obj = hits.get("total") or {}
    total = total_obj.get("value", 0) if isinstance(total_obj, dict) else 0
    rows = [
        {"id": h.get("_id"), **(h.get("_source") or {})}
        for h in (hits.get("hits") or [])
    ]
    nxt = after + len(rows)
    return {"total": total, "rows": rows, "next": nxt if nxt < total else None}


def _normalized_keys(field: str, value: str) -> tuple[str, list[str]]:
    """告警主体 → (查哪个索引的哪个字段, 归一化后的键)。

    口径必须和 `sources/csv_source.lookup` 一致：主机查 assets.keys、IP 查 assets.ip、
    用户查 identities.user_key。不一致的话覆盖率会报出一个和实际解析结果对不上的数。
    """
    f = (field or "").lower()
    if f.startswith("user"):
        u = normalize_user(value)
        return ("user_key", [u] if u else [])
    if "ip" in f:
        ip = normalize_ip(value)
        return ("ip", [ip] if ip else [])
    return ("keys", normalize_host(value))


async def coverage(es) -> dict[str, Any]:
    """最近的告警里，主体能在资产/身份表里查到的比例。

    这是「导完 CSV 到底有没有生效」的那个数。分母只算**有主体**的告警：没有主体的
    告警（比如只有一条规则名的聚合告警）本来就无从匹配，算进分母会把覆盖率压低成
    一个没法改善的数字，看的人会以为是自己表没导好。
    """
    out: dict[str, Any] = {
        "sampled": 0, "with_subject": 0, "matched": 0, "ratio": None,
    }
    try:
        resp = await es.search(
            index=_alerts_index(),
            body={
                "size": _COVERAGE_SAMPLE,
                "sort": [{"@timestamp": "desc"}],
                "_source": ["subject_field", "subject_value"],
                "query": {"match_all": {}},
            },
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("coverage sample failed: %s", e)
        return out

    res = getattr(resp, "body", resp)
    hits = ((res.get("hits") or {}).get("hits") or []) if isinstance(res, dict) else []
    out["sampled"] = len(hits)

    # 先按 (字段, 键) 去重再查：500 条告警里往往只有几十个不同的主体，逐条查是几百次
    # 无谓的往返。
    wanted: dict[str, set[str]] = {"keys": set(), "ip": set(), "user_key": set()}
    subjects: list[tuple[str, tuple[str, ...]]] = []
    for h in hits:
        src = h.get("_source") or {}
        value = str(src.get("subject_value") or "").strip()
        if not value:
            continue
        field, keys = _normalized_keys(str(src.get("subject_field") or ""), value)
        if not keys:
            continue
        subjects.append((field, tuple(keys)))
        wanted[field].update(keys)

    out["with_subject"] = len(subjects)
    if not subjects:
        return out

    found: dict[str, set[str]] = {"keys": set(), "ip": set(), "user_key": set()}
    for field, keys in wanted.items():
        if not keys:
            continue
        index = IDENTITIES_INDEX if field == "user_key" else ASSETS_INDEX
        try:
            resp = await es.search(
                index=index,
                body={
                    "size": 0,
                    "query": {"terms": {f"{field}.keyword": sorted(keys)}},
                    # 回来的是「表里确实存在的那些键」，一次聚合换一次 N 条查询。
                    "aggs": {"present": {"terms": {"field": f"{field}.keyword", "size": len(keys)}}},
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("coverage lookup failed on %s: %s", index, e)
            continue
        res = getattr(resp, "body", resp)
        buckets = (((res.get("aggregations") or {}).get("present") or {}).get("buckets") or [])
        found[field].update(str(b.get("key")) for b in buckets)

    matched = sum(1 for field, keys in subjects if any(k in found[field] for k in keys))
    out["matched"] = matched
    out["ratio"] = round(matched / len(subjects), 3)
    return out


async def summary(es) -> dict[str, Any]:
    """两张表各有多少行 + 覆盖率。页面顶部那一行读的就是这个。"""
    counts: dict[str, int] = {}
    for kind in KINDS:
        try:
            resp = await es.count(index=_index(kind))
            body = getattr(resp, "body", resp)
            counts[kind] = int(body.get("count", 0)) if isinstance(body, dict) else 0
        except Exception:  # noqa: BLE001 — 索引不存在 = 还没导过 = 0
            counts[kind] = 0
    return {"counts": counts, "coverage": await coverage(es)}
