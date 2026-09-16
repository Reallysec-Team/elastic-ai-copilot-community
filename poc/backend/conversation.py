"""Conversation state for multi-turn DSL generation.

Two interchangeable backends behind one async interface:

  * memory (default) — bounded LRU dict, max 200 conversations, 1h idle TTL.
    Zero-config, but state is lost on restart and not shared across workers.

  * es — one document per conversation in an Elasticsearch index. Survives
    gateway restarts and is shared across multiple workers / replicas. Enable
    with `RST_CONVERSATION_BACKEND=es` (optionally `RST_CONVERSATION_INDEX`,
    `RST_CONVERSATION_TTL_DAYS`). ES errors degrade gracefully — a hiccup
    means "no multi-turn memory for this request", never a failed /api/generate.

Callers use the module-level functions and never see which backend is active.

轮次的生命周期（2026-09-15 起）：
    open_turn   问题发出去的那一刻就落一条 status=pending 的轮次；会话不存在时，
                会话和这第一轮**同一次写入**——结构上不再有「有壳没轮次」的空会话。
    settle_turn 流结束改 done（补 dsl / explanation），出错改 failed（存 error），
                客户端断开改 aborted。失败也是历史：用户问过、答失败了，这一问
                要留着，能重试。
    reap_stale  网关中途挂掉会留下永远 pending 的轮次；启动时 + 定期把超过
                PENDING_STALE_S 的 pending 改成 failed(timeout)，顺手删掉老版本
                留下的 0 轮次空壳。
"""

import asyncio
import logging
import os
import time
import uuid
from collections import OrderedDict
from typing import Any

from . import user_db

logger = logging.getLogger("rst.conversation")

MAX_CONVERSATIONS = 200
TURN_RETAIN = 4
TTL_SECONDS = 3600  # in-memory idle TTL

TURN_PENDING = "pending"
TURN_DONE = "done"
TURN_FAILED = "failed"
TURN_ABORTED = "aborted"
TURN_STATUSES = (TURN_PENDING, TURN_DONE, TURN_FAILED, TURN_ABORTED)
# pending 超过这么久没人来 settle，就当网关当时挂了。生成本身有 45s 首字上限 +
# 180s 供应商超时，10 分钟够宽。
PENDING_STALE_S = 600


def new_id() -> str:
    return uuid.uuid4().hex


# 归属判定在 `user_db` 里 —— 这两个存储各写过一份一模一样的，而那一份要知道
# 「这个部署配没配用户表」才能决定空 owner 放不放行。
_owner_matches = user_db.owner_matches


# ─────────────────────────────── backend selection ───────────────────────────────


def _use_es() -> bool:
    return os.environ.get("RST_CONVERSATION_BACKEND", "").strip().lower() == "es"


def _es_index() -> str:
    return os.environ.get("RST_CONVERSATION_INDEX", "").strip() or ".rst_copilot_conversations"


# 显式映射。owner 现在靠动态映射长出 `owner.keyword` —— 也就是说这条按人隔离的
# 过滤，取决于「谁先写进去、ES 猜成了什么」。客户那边只要有一个 index template 把
# 这个索引名罩住、把 owner 定成别的类型，`{"term": {"owner.keyword": …}}` 就永远
# 匹配不上：历史列表对每个账号恒空，而且不报错。analysis_store 已经踩过一次
# （见那边 _INDEX_MAPPING 上面的注释），这里补上同一道保险。
#
# owner 定成 keyword，同时留一个同名的 `keyword` 子字段：查询路径仍旧写
# `owner.keyword`，所以老索引（动态映射出来的 text+keyword）和新索引都走同一条、
# 且两边都是精确匹配 —— 不需要迁移，也不需要在查询里 or 两个字段名。
_INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "owner": {"type": "keyword", "fields": {"keyword": {"type": "keyword"}}},
            "created_at": {"type": "double"},
            "last_at": {"type": "double"},
            "turns": {"type": "object", "enabled": False},
        }
    }
}

_index_ready = False


async def _ensure_es_index(es) -> None:
    """建索引（带显式映射）。best-effort、幂等：已存在的索引一个字都不动。"""
    global _index_ready
    if _index_ready:
        return
    try:
        if not await es.indices.exists(index=_es_index()):
            await es.indices.create(index=_es_index(), body=_INDEX_MAPPING)
        _index_ready = True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"conversation index ensure failed: {e}")


def _reset_index_ready_for_tests() -> None:
    global _index_ready
    _index_ready = False


def _es_ttl_seconds() -> float:
    try:
        days = float(os.environ.get("RST_CONVERSATION_TTL_DAYS", "").strip())
        if days > 0:
            return days * 86400
    except (TypeError, ValueError):
        pass
    return 7 * 86400


# ─────────────────────────────── public async API ───────────────────────────────


async def get(conv_id: str, owner: str | None = None) -> dict[str, Any] | None:
    entry = await _es_get(conv_id) if _use_es() else await _mem_get(conv_id)
    if entry is None:
        return None
    if not _owner_matches(entry.get("owner"), owner):
        return None
    return entry


async def get_or_create(
    conv_id: str | None, owner: str | None = None
) -> tuple[str, dict[str, Any]]:
    if _use_es():
        return await _es_get_or_create(conv_id, owner)
    return await _mem_get_or_create(conv_id, owner)


async def append_turn(conv_id: str, turn: dict[str, Any], owner: str | None = None) -> None:
    """一步落一条已完成的轮次（非流式路径 / 测试）。等价于 open + settle(done)。"""
    record = {"turn_id": new_id(), "status": TURN_DONE, "settled_at": time.time(), **turn}
    if _use_es():
        await _es_append_turn(conv_id, record, owner)
        return
    await _mem_append_turn(conv_id, record, owner)


def _new_pending(turn: dict[str, Any]) -> dict[str, Any]:
    return {"turn_id": new_id(), "timestamp": time.time(), "status": TURN_PENDING, **turn}


async def open_turn(
    conv_id: str | None, turn: dict[str, Any], owner: str | None = None
) -> tuple[str, str]:
    """问题发出去：落一条 pending 轮次。会话不存在（或不是自己的）就连会话一起建。
    返回 (conv_id, turn_id)。"""
    record = _new_pending(turn)
    if _use_es():
        cid = await _es_open_turn(conv_id, record, owner)
    else:
        cid = await _mem_open_turn(conv_id, record, owner)
    return cid, record["turn_id"]


async def settle_turn(
    conv_id: str, turn_id: str, status: str, fields: dict[str, Any] | None = None,
    owner: str | None = None,
) -> None:
    """把一条 pending 轮次收尾：done / failed / aborted，附带 dsl / error 等字段。
    找不到轮次（会话过期、被删、ES 抖了）就算了——收尾失败不该让请求失败。"""
    if status not in TURN_STATUSES:
        raise ValueError(f"bad turn status {status!r}")
    patch = {**(fields or {}), "status": status, "settled_at": time.time()}
    if _use_es():
        await _es_settle_turn(conv_id, turn_id, patch, owner)
        return
    await _mem_settle_turn(conv_id, turn_id, patch, owner)


def turns_for_prompt(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """给模型看的历史：只要成功且有 DSL 的轮次。失败 / 中断的问题没有可延续的
    查询，喂进去只会让模型把上一轮的错误当上下文。"""
    return [t for t in turns if t.get("status", TURN_DONE) == TURN_DONE and t.get("dsl")]


async def reap_stale() -> dict[str, int]:
    """pending 超时 → failed(timeout)；0 轮次的空壳 → 删。返回 {"timed_out", "empties"}。"""
    if _use_es():
        return await _es_reap_stale()
    return await _mem_reap_stale()


def _stale_patch() -> dict[str, Any]:
    return {
        "status": TURN_FAILED,
        "settled_at": time.time(),
        "error": {"code": "turn_reaped", "message": "网关未能完成这一轮（可能在生成时重启了）"},
    }


async def delete(conv_id: str, owner: str | None = None) -> bool:
    # Owner-scoped delete: only the owner may remove their conversation.
    if owner is not None and await get(conv_id, owner) is None:
        return False
    if _use_es():
        return await _es_delete(conv_id)
    return await _mem_delete(conv_id)


async def list_all(limit: int = 30, offset: int = 0, owner: str | None = None) -> dict[str, Any]:
    if _use_es():
        return await _es_list_all(limit, offset, owner)
    return await _mem_list_all(limit, offset, owner)


# ─────────────────────────────── in-memory backend ───────────────────────────────

_store: OrderedDict[str, dict[str, Any]] = OrderedDict()
_lock = asyncio.Lock()


async def _mem_get(conv_id: str) -> dict[str, Any] | None:
    async with _lock:
        entry = _store.get(conv_id)
        if not entry:
            return None
        if time.time() - entry["last_at"] > TTL_SECONDS:
            del _store[conv_id]
            return None
        _store.move_to_end(conv_id)
        return _copy(entry)


async def _mem_get_or_create(
    conv_id: str | None, owner: str | None = None
) -> tuple[str, dict[str, Any]]:
    if conv_id:
        existing = await _mem_get(conv_id)
        if existing and _owner_matches(existing.get("owner"), owner):
            return conv_id, existing
    new = new_id()
    async with _lock:
        _store[new] = {
            "id": new,
            "owner": owner,
            "turns": [],
            "last_at": time.time(),
            "created_at": time.time(),
        }
        _store.move_to_end(new)
        _evict_locked()
        return new, _copy(_store[new])


async def _mem_append_turn(conv_id: str, turn: dict[str, Any], owner: str | None = None) -> None:
    async with _lock:
        entry = _store.get(conv_id)
        if not entry:
            return
        if not _owner_matches(entry.get("owner"), owner):
            return
        record = {"timestamp": time.time(), **turn}
        entry["turns"].append(record)
        entry["turns"] = entry["turns"][-TURN_RETAIN:]
        entry["last_at"] = time.time()
        _store.move_to_end(conv_id)


async def _mem_open_turn(conv_id: str | None, record: dict[str, Any], owner: str | None) -> str:
    async with _lock:
        entry = _store.get(conv_id) if conv_id else None
        if entry and (time.time() - entry["last_at"] > TTL_SECONDS or not _owner_matches(entry.get("owner"), owner)):
            entry = None
        if entry is None:
            cid = new_id()
            now = time.time()
            entry = {"id": cid, "owner": owner, "turns": [], "last_at": now, "created_at": now}
            _store[cid] = entry
        entry["turns"].append(record)
        entry["turns"] = entry["turns"][-TURN_RETAIN:]
        entry["last_at"] = time.time()
        _store.move_to_end(entry["id"])
        _evict_locked()
        return entry["id"]


async def _mem_settle_turn(conv_id: str, turn_id: str, patch: dict[str, Any], owner: str | None) -> None:
    async with _lock:
        entry = _store.get(conv_id)
        if not entry or not _owner_matches(entry.get("owner"), owner):
            return
        for t in entry["turns"]:
            if t.get("turn_id") == turn_id:
                t.update(patch)
                entry["last_at"] = time.time()
                return


async def _mem_reap_stale() -> dict[str, int]:
    timed_out = empties = 0
    cutoff = time.time() - PENDING_STALE_S
    async with _lock:
        for cid in list(_store):
            entry = _store[cid]
            if not entry["turns"]:
                del _store[cid]
                empties += 1
                continue
            for t in entry["turns"]:
                if t.get("status") == TURN_PENDING and float(t.get("timestamp") or 0) < cutoff:
                    t.update(_stale_patch())
                    timed_out += 1
    return {"timed_out": timed_out, "empties": empties}


async def _mem_delete(conv_id: str) -> bool:
    async with _lock:
        return _store.pop(conv_id, None) is not None


async def _mem_list_all(limit: int, offset: int, owner: str | None = None) -> dict[str, Any]:
    """Return summaries of all live conversations, newest first."""
    async with _lock:
        # 先按 TTL 清一遍：`_mem_get` 读到过期项会当场删掉并返回 None，列表却
        # 一直把它们列出来——用户在切换器里点开 1 小时前的会话就是 404。列表和
        # 单条读必须是同一个「还活着」的定义。
        _evict_locked()
        # Newest first — _store is LRU, so iterate reversed.
        items = [e for e in reversed(_store.values()) if _owner_matches(e.get("owner"), owner)]
        total = len(items)
        page = items[offset : offset + limit]
        summaries = [_summary(e) for e in page]
        return {"total": total, "conversations": summaries}


def _evict_locked() -> None:
    while len(_store) > MAX_CONVERSATIONS:
        _store.popitem(last=False)
    now = time.time()
    expired = [k for k, v in _store.items() if now - v["last_at"] > TTL_SECONDS]
    for k in expired:
        _store.pop(k, None)


def _copy(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry["id"],
        "owner": entry.get("owner"),
        "turns": [dict(t) for t in entry["turns"]],
        "last_at": entry["last_at"],
        "created_at": entry["created_at"],
    }


def _summary(e: dict[str, Any]) -> dict[str, Any]:
    turns = e.get("turns") or []
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "last_at": e["last_at"],
        "turn_count": len(turns),
        "first_question": (turns[0]["question"] if turns else None),
        # 列表上给个状态点：最后一轮失败 / 中断 / 还在跑。老记录没有 status，按 done。
        "last_status": (turns[-1].get("status", TURN_DONE) if turns else None),
    }


# ─────────────────────────────── elasticsearch backend ───────────────────────────────
#
# One doc per conversation: {id, turns[], created_at, last_at}. Reads filter out
# docs older than the TTL; a periodic delete-by-query isn't required for
# correctness (expired docs are simply never returned) but operators may prune
# the index on their own schedule.


def _es_expired(entry: dict[str, Any]) -> bool:
    last_at = entry.get("last_at") or 0
    return (time.time() - float(last_at)) > _es_ttl_seconds()


async def _es_get(conv_id: str) -> dict[str, Any] | None:
    from elasticsearch import NotFoundError

    from .es_client import get_es

    try:
        resp = await get_es().get(index=_es_index(), id=conv_id)
    except NotFoundError:
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"conversation ES get failed ({conv_id}): {e}")
        return None
    body = getattr(resp, "body", resp)
    if not isinstance(body, dict) or not body.get("found"):
        return None
    src = body.get("_source") or {}
    if _es_expired(src):
        return None
    return {
        "id": src.get("id", conv_id),
        "owner": src.get("owner"),
        "turns": list(src.get("turns") or []),
        "last_at": src.get("last_at"),
        "created_at": src.get("created_at"),
    }


async def _es_get_or_create(
    conv_id: str | None, owner: str | None = None
) -> tuple[str, dict[str, Any]]:
    if conv_id:
        existing = await _es_get(conv_id)
        if existing and _owner_matches(existing.get("owner"), owner):
            return conv_id, existing
    from .es_client import get_es

    new = new_id()
    now = time.time()
    doc = {"id": new, "owner": owner, "turns": [], "created_at": now, "last_at": now}
    try:
        await _ensure_es_index(get_es())
        await get_es().index(index=_es_index(), id=new, document=doc, refresh="wait_for")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"conversation ES create failed ({new}): {e}")
    return new, dict(doc)


async def _es_mutate_turns(conv_id: str, owner: str | None, mutate, what: str) -> bool:
    """读-改-写一条会话的 turns。`mutate(turns) -> turns | None`（None = 没什么可改）。

    Optimistic concurrency: read seq_no/primary_term with the doc and require
    them on update, so a concurrent write on another worker doesn't get its
    turn silently overwritten. On a version conflict, re-read and retry.
    返回是否写成功；会话不存在 / 不是自己的 / ES 抖了都返回 False（只记 warning）。
    """
    from elasticsearch import ConflictError, NotFoundError

    from .es_client import get_es

    es = get_es()
    for _ in range(3):
        try:
            resp = await es.get(index=_es_index(), id=conv_id)
        except NotFoundError:
            return False
        except Exception as e:  # noqa: BLE001
            logger.warning(f"conversation ES {what} read failed ({conv_id}): {e}")
            return False
        body = getattr(resp, "body", resp)
        if not isinstance(body, dict) or not body.get("found"):
            return False
        src = body.get("_source") or {}
        if not _owner_matches(src.get("owner"), owner) or _es_expired(src):
            return False
        turns = mutate(list(src.get("turns") or []))
        if turns is None:
            return False
        try:
            await es.update(
                index=_es_index(),
                id=conv_id,
                doc={"turns": turns[-TURN_RETAIN:], "last_at": time.time()},
                refresh="wait_for",
                if_seq_no=body.get("_seq_no"),
                if_primary_term=body.get("_primary_term"),
            )
            return True
        except ConflictError:
            continue  # lost the race — re-read and retry
        except Exception as e:  # noqa: BLE001
            logger.warning(f"conversation ES {what} failed ({conv_id}): {e}")
            return False
    logger.warning(f"conversation ES {what} gave up after retries ({conv_id})")
    return False


async def _es_append_turn(conv_id: str, turn: dict[str, Any], owner: str | None = None) -> None:
    record = {"timestamp": time.time(), **turn}
    await _es_mutate_turns(conv_id, owner, lambda ts: ts + [record], "append")


async def _es_open_turn(conv_id: str | None, record: dict[str, Any], owner: str | None) -> str:
    if conv_id and await _es_mutate_turns(conv_id, owner, lambda ts: ts + [record], "open"):
        return conv_id
    # 没有可续的会话：会话 + 第一轮一次写入。
    from .es_client import get_es

    cid = new_id()
    now = time.time()
    doc = {"id": cid, "owner": owner, "turns": [record], "created_at": now, "last_at": now}
    try:
        await _ensure_es_index(get_es())
        await get_es().index(index=_es_index(), id=cid, document=doc, refresh="wait_for")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"conversation ES create failed ({cid}): {e}")
    return cid


async def _es_settle_turn(conv_id: str, turn_id: str, patch: dict[str, Any], owner: str | None) -> None:
    def _apply(turns: list[dict[str, Any]]):
        hit = False
        for t in turns:
            if t.get("turn_id") == turn_id:
                t.update(patch)
                hit = True
        return turns if hit else None

    await _es_mutate_turns(conv_id, owner, _apply, "settle")


async def _es_reap_stale() -> dict[str, int]:
    """pending 超时的轮次改 failed；0 轮次的空壳删掉。

    turns 在映射里是 enabled=false（不索引），查不了 turns.status——所以是一把
    update_by_query 扫全部未过期文档，painless 里判断：没轮次的 ctx.op=delete，
    有超时 pending 的改状态，其余 noop。一个网关的会话是几百条的量级，扫得起。
    """
    from .es_client import get_es

    out = {"timed_out": 0, "empties": 0}
    cutoff = time.time() - PENDING_STALE_S
    patch = _stale_patch()
    try:
        resp = await get_es().update_by_query(
            index=_es_index(),
            query={"range": {"last_at": {"gte": time.time() - _es_ttl_seconds()}}},
            script={
                "lang": "painless",
                "source": (
                    "def turns = ctx._source.turns;"
                    "if (turns == null || turns.isEmpty()) { ctx.op = 'delete'; return; }"
                    "boolean changed = false;"
                    "for (t in turns) {"
                    "  if (t.status == 'pending' && t.timestamp != null && t.timestamp < params.cutoff) {"
                    "    t.status = params.status; t.settled_at = params.now; t.error = params.error;"
                    "    changed = true;"
                    "  }"
                    "}"
                    "if (!changed) { ctx.op = 'noop'; }"
                ),
                "params": {"cutoff": cutoff, "now": patch["settled_at"],
                           "status": patch["status"], "error": patch["error"]},
            },
            conflicts="proceed",
            refresh=True,
        )
        body = getattr(resp, "body", resp)
        if isinstance(body, dict):
            out["timed_out"] = int(body.get("updated") or 0)
            out["empties"] = int(body.get("deleted") or 0)
    except Exception as e:  # noqa: BLE001
        if "index_not_found_exception" not in str(e):
            logger.warning(f"conversation ES reap failed: {e}")
    if out["timed_out"] or out["empties"]:
        logger.info("conversation reap", extra=out)
    return out


async def _es_delete(conv_id: str) -> bool:
    from elasticsearch import NotFoundError

    from .es_client import get_es

    try:
        resp = await get_es().delete(index=_es_index(), id=conv_id)
    except NotFoundError:
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning(f"conversation ES delete failed ({conv_id}): {e}")
        return False
    body = getattr(resp, "body", resp)
    return isinstance(body, dict) and body.get("result") == "deleted"


# 过期文档的清理节流：列表按 last_at 过滤了过期项，但文档本身从来没人删，
# 客户集群里只增不减。不另起调度器——列表请求顺手带一次 delete_by_query，
# 一小时最多一次；ES 挂了就算了，下次再来。
_PURGE_INTERVAL_S = 3600
_last_purge_at = 0.0


async def _es_purge_expired(es, cutoff: float) -> int:
    global _last_purge_at
    now = time.time()
    if now - _last_purge_at < _PURGE_INTERVAL_S:
        return 0
    _last_purge_at = now
    await _es_reap_stale()
    try:
        resp = await es.delete_by_query(
            index=_es_index(),
            query={"range": {"last_at": {"lt": cutoff}}},
            conflicts="proceed",
        )
    except Exception as e:  # noqa: BLE001
        if "index_not_found_exception" not in str(e):
            logger.warning(f"conversation ES purge failed: {e}")
        return 0
    body = getattr(resp, "body", resp)
    deleted = int((body or {}).get("deleted") or 0) if isinstance(body, dict) else 0
    if deleted:
        logger.info(f"conversation ES purge: {deleted} expired")
    return deleted


def _reset_purge_for_tests() -> None:
    global _last_purge_at
    _last_purge_at = 0.0


async def _es_list_all(limit: int, offset: int, owner: str | None = None) -> dict[str, Any]:
    from .es_client import get_es

    cutoff = time.time() - _es_ttl_seconds()
    await _es_purge_expired(get_es(), cutoff)
    must: list[dict[str, Any]] = [{"range": {"last_at": {"gte": cutoff}}}]
    if owner is not None:
        # Dynamic-mapped index: exact match lives on the .keyword subfield.
        must.append({"term": {"owner.keyword": owner}})
    body = {
        "query": {"bool": {"filter": must}},
        "sort": [{"last_at": "desc"}],
        "from": offset,
        "size": limit,
        "track_total_hits": True,
    }
    try:
        resp = await get_es().search(index=_es_index(), body=body)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"conversation ES list failed: {e}")
        return {"total": 0, "conversations": []}
    res = getattr(resp, "body", resp)
    hits = (res.get("hits") or {}) if isinstance(res, dict) else {}
    total_obj = hits.get("total") or {}
    total = total_obj.get("value", 0) if isinstance(total_obj, dict) else 0
    summaries = [_summary(h.get("_source") or {}) for h in (hits.get("hits") or [])]
    return {"total": total, "conversations": summaries}
