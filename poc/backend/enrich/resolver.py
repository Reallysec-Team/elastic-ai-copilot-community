"""Single resolver, gradient lookup chain, 命中即返回:
    enrich (0-query)
      → Entity Store   [best-effort]
      → Asset Criticality [best-effort]
      → CSV indices    [保底]
      → None (unresolved — never fake precision)
host/user (stable keys) are tried before IP. Results are cached in-process by
normalized entity key with a short TTL time bucket.

# ponytail: plain dict + monotonic-time TTL — @lru_cache can't wrap an async fn.
# In-process single-node cache; multi-replica each caches its own — acceptable.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

from .entity import AssetContext, Entity, extract_entities
from .sources import criticality, csv_source, enrich_source, entity_store

_TTL_SECONDS = 300

# Keys are entity *values* (every distinct IP, user and host the gateway ever
# enriches), and the TTL is only consulted on read — so an entity seen once and
# never again stayed resident forever. Over months of alert traffic that is
# unbounded growth in a long-lived container, not a cache. Cap it and evict
# least-recently-used.
_MAX_ENTRIES = 10_000

# key -> (expiry_epoch, AssetContext | None). None is cached too (negative cache).
_cache: OrderedDict[str, tuple[float, AssetContext | None]] = OrderedDict()


def _cache_put(key: str, value: tuple[float, AssetContext | None]) -> None:
    _cache[key] = value
    _cache.move_to_end(key)
    while len(_cache) > _MAX_ENTRIES:
        _cache.popitem(last=False)

# ES-querying sources, in gradient order after enrich.
_ES_SOURCES = (entity_store.lookup, criticality.lookup, csv_source.lookup)


def clear_cache() -> None:
    _cache.clear()


def _cache_key(ent: Entity) -> str:
    return f"{ent.kind}:{'|'.join(ent.keys)}"


async def _resolve_entity(ent: Entity, es) -> AssetContext | None:
    for src in _ES_SOURCES:
        ctx = await src(ent, es)
        if ctx:
            return ctx
    return None


async def resolve(
    raw: dict[str, Any], es, *, now: float | None = None
) -> AssetContext | None:
    now = time.monotonic() if now is None else now

    # 1) enrich direct read — 0 ES query, highest priority.
    ctx = enrich_source.from_doc(raw)
    if ctx:
        return ctx

    # 2) entities in priority order (host, user, ip); first hit wins.
    for ent in extract_entities(raw):
        key = _cache_key(ent)
        cached = _cache.get(key)
        if cached and cached[0] > now:
            _cache.move_to_end(key)  # keep hot keys away from the LRU tail
            if cached[1]:
                return cached[1]
            continue  # negative cache hit — skip to next entity
        result = await _resolve_entity(ent, es)
        _cache_put(key, (now + _TTL_SECONDS, result))
        if result:
            return result
    return None
