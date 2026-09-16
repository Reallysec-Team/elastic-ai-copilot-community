"""Analysis archive — persist investigation & triage results for later review.

ES-only, best-effort: any ES hiccup degrades to "not recorded", never a failed
analysis response. Owner isolation and TTL mirror conversation.py.
"""

import logging
import os
import time
import uuid
from typing import Any

from . import user_db

logger = logging.getLogger("rst.analysis")

SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]


def _index() -> str:
    return os.environ.get("RST_ANALYSIS_INDEX", "").strip() or ".rst_copilot_analysis"


def _ttl_seconds() -> float:
    try:
        days = float(os.environ.get("RST_ANALYSIS_TTL_DAYS", "").strip())
        if days > 0:
            return days * 86400
    except (TypeError, ValueError):
        pass
    return 30 * 86400


# 归属判定在 `user_db` 里 —— 这两个存储各写过一份一模一样的，而那一份要知道
# 「这个部署配没配用户表」才能决定空 owner 放不放行。
_owner_matches = user_db.owner_matches


def _clip(s: Any, n: int) -> str:
    return (str(s) if s is not None else "")[:n]


def _max_severity(sevs: list[Any]) -> str:
    best = "info"
    for s in sevs:
        if s in SEVERITY_ORDER and SEVERITY_ORDER.index(s) > SEVERITY_ORDER.index(best):
            best = s
    return best


def _derive(kind: str, doc: dict) -> dict:
    if not isinstance(doc, dict):
        doc = {}
    if kind == "triage":
        clusters = doc.get("clusters") if isinstance(doc.get("clusters"), list) else []
        total = doc.get("total_clusters")
        n = total if isinstance(total, int) else len(clusters)
        top = clusters[0] if clusters else {}
        return {
            "title": f"{n} 个 cluster 分诊",
            "summary": _clip(top.get("recommendation"), 400),
            "severity": _max_severity([c.get("severity") for c in clusters if isinstance(c, dict)]),
            "subject": {"type": "triage", "value": f"{n} clusters"},
        }
    if kind == "result_explain":
        # A query-result interpretation. `log_type` is the model's one-line
        # verdict on the result set ("认证失败统计", "无攻击相关有效信号"), which
        # is the most useful thing to show in an archive list.
        sev = doc.get("severity")
        return {
            "title": _clip(doc.get("log_type"), 40) or "查询结果解读",
            "summary": _clip(doc.get("summary"), 400),
            "severity": sev if sev in SEVERITY_ORDER else "info",
            "subject": {"type": "query", "value": _clip(doc.get("question"), 120)},
        }
    # investigation
    assets = doc.get("affected_assets") if isinstance(doc.get("affected_assets"), list) else []
    first = assets[0] if assets and isinstance(assets[0], dict) else {}
    sev = doc.get("severity")
    return {
        "title": _clip(doc.get("alert_type") or doc.get("summary"), 40) or "unknown",
        "summary": _clip(doc.get("summary"), 400),
        "severity": sev if sev in SEVERITY_ORDER else "info",
        "subject": {"type": _clip(first.get("type"), 20) or "unknown",
                    "value": _clip(first.get("id"), 120)},
    }


# 建索引时把 payload 定成「存下来但不索引」。
#
# 之前这个索引是靠动态映射长出来的：ES 从前几条记录里推出
# payload.timeline.time 是 date，之后模型只要写一个时间区间
# （"...23:49:17Z ~ 23:50:05Z"），整条记录就被 document_parsing_exception 拒掉，
# 日志里一行 WARNING，界面上调查结果照常显示 —— 归档里却什么都没有。
#
# payload 是给人看的原始结论，没有任何地方按它的内部字段检索（列表和详情读的是
# 外层那几个 derived 字段），所以 enabled: false 是它本来就该有的形状：怎么写都
# 不会再有映射冲突。告警存储对 raw 用的是同一招。
_INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "kind": {"type": "keyword"},
            "created_at": {"type": "double"},
            "owner": {"type": "keyword"},
            "masking_mode": {"type": "keyword"},
            "degraded": {"type": "boolean"},
            "title": {"type": "text"},
            "summary": {"type": "text"},
            "severity": {"type": "keyword"},
            "subject": {
                "properties": {"type": {"type": "keyword"}, "value": {"type": "keyword"}}
            },
            "payload": {"type": "object", "enabled": False},
        }
    }
}

_index_ready = False


async def _ensure_index(es) -> None:
    """Create the archive index with an explicit mapping. Best-effort and
    idempotent: an existing index (including one with the old dynamic mapping)
    is left exactly as it is."""
    global _index_ready
    if _index_ready:
        return
    try:
        if not await es.indices.exists(index=_index()):
            await es.indices.create(index=_index(), body=_INDEX_MAPPING)
    except Exception as e:  # noqa: BLE001
        # 「已经存在」是抢建输了，等于成功；其它失败（最常见的是网关比 ES 先起来，
        # 客户自带 ELK 的部署里是常态）必须留给下次重试。原来这里无论成败都置位，
        # 结果是 ES 恢复后第一次写由**动态映射**建索引：owner 变成 text，
        # `{"term": {"owner": …}}` 再也匹配不上（分析记录页对这些用户恒空），
        # payload 也丢掉 "enabled": false，字段数迟早撞上 1000 上限。
        if not _is_already_exists(e):
            logger.warning("analysis_index_ensure_failed", extra={"error": str(e)[:200]})
            return
    _index_ready = True


def _is_already_exists(e: Exception) -> bool:
    """True 只在「索引已存在」时 —— 别把真正的 400（比如映射写错了）也吞掉。"""
    text = str(e).lower()
    return "resource_already_exists" in text or "already exists" in text


async def record(kind: str, doc: dict, owner: str | None = None, es=None) -> str | None:
    from .field_masking import current_mode

    if es is None:
        from .es_client import get_es
        es = get_es()
    rec_id = uuid.uuid4().hex
    derived = _derive(kind, doc)
    record_doc = {
        "id": rec_id,
        "kind": kind,
        "created_at": time.time(),
        "owner": owner,
        "masking_mode": current_mode(),
        "degraded": bool(doc.get("degraded")) if isinstance(doc, dict) else False,
        "payload": doc,
        **derived,
    }
    try:
        await _ensure_index(es)
        await es.index(index=_index(), id=rec_id, document=record_doc, refresh="wait_for")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"analysis record failed ({kind}): {e}")
        return None
    return rec_id


_SUMMARY_FIELDS = ("id", "kind", "created_at", "title", "summary", "severity", "subject")


def _summary(src: dict) -> dict:
    return {k: src.get(k) for k in _SUMMARY_FIELDS}


def _expired(created_at: Any) -> bool:
    try:
        return (time.time() - float(created_at)) > _ttl_seconds()
    except (TypeError, ValueError):
        return False


async def list_records(
    kind: str | None,
    limit: int,
    before: float | None,
    owner: str | None,
    es=None,
    q: str | None = None,
    since: float | None = None,
) -> dict:
    if es is None:
        from .es_client import get_es
        es = get_es()
    # TTL 是硬下界：过期的记录一律不返回，`since` 只能在它之上再收窄，不能放宽。
    created_range: dict[str, float] = {"gte": time.time() - _ttl_seconds()}
    if since is not None:
        created_range["gte"] = max(created_range["gte"], since)
    if before is not None:
        created_range["lt"] = before
    filters: list[dict[str, Any]] = [{"range": {"created_at": created_range}}]
    if owner is not None:
        # 按 owner 本体查，不是 owner.keyword —— 上面 _INDEX_MAPPING 把 owner 显式
        # 声明成 keyword，没有 .keyword 子字段（那是动态映射给 text 加的）。查一个
        # 不存在的字段永远匹配不到，归档列表对所有人恒返回空。
        filters.append({"term": {"owner": owner}})
    if kind:
        filters.append({"term": {"kind": kind}})
    if q and q.strip():
        # 只打 title + summary 两个 text 字段 —— 归档列表上能看见的就是这两样，
        # 搜出一条在屏幕上找不到关键词的记录比搜不到更让人困惑。
        # simple_query_string 而不是 query_string：它对用户随手打的引号、冒号、
        # 中括号不报 400，最坏情况是当成普通字符去匹配。
        filters.append({
            "simple_query_string": {
                "query": q.strip(),
                "fields": ["title", "summary"],
                "default_operator": "and",
            }
        })
    body = {
        "query": {"bool": {"filter": filters}},
        "sort": [{"created_at": "desc"}],
        "size": limit,
        "track_total_hits": True,
    }
    try:
        resp = await es.search(index=_index(), body=body)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"analysis list failed: {e}")
        return {"total": 0, "records": []}
    res = getattr(resp, "body", resp)
    hits = (res.get("hits") or {}) if isinstance(res, dict) else {}
    total_obj = hits.get("total") or {}
    total = total_obj.get("value", 0) if isinstance(total_obj, dict) else 0
    records = [_summary(h.get("_source") or {}) for h in (hits.get("hits") or [])]
    return {"total": total, "records": records}


async def get_record(rec_id: str, owner: str | None = None, es=None) -> dict | None:
    from elasticsearch import NotFoundError

    if es is None:
        from .es_client import get_es
        es = get_es()
    try:
        resp = await es.get(index=_index(), id=rec_id)
    except NotFoundError:
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"analysis get failed ({rec_id}): {e}")
        return None
    body = getattr(resp, "body", resp)
    if not isinstance(body, dict) or not body.get("found"):
        return None
    src = body.get("_source") or {}
    if not _owner_matches(src.get("owner"), owner):
        return None
    if _expired(src.get("created_at")):
        return None
    return src
