"""Tiny in-process TTL cache for deterministic LLM results.

Two analysts asking the same question against the same index used to each pay a
full LLM round-trip (latency + token cost). Generation runs at temperature 0, so
for a given (question, index, mapping) the answer is stable — safe to memoise for
a short window. The cache key folds in a fingerprint of the index mapping, so a
mapping change (new field, reindex) transparently busts stale entries.

Single-process only. With multiple workers each keeps its own cache — still a
net win, and avoids a hard Redis dependency. Disable with RST_DSL_CACHE_TTL_S=0.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import OrderedDict
from typing import Any

_MAX_ENTRIES = 256

# key -> (expires_at_epoch, value)
_store: OrderedDict[str, tuple[float, Any]] = OrderedDict()


def _ttl_seconds() -> float:
    raw = os.environ.get("RST_DSL_CACHE_TTL_S", "").strip()
    if raw == "":
        return 600.0  # default: 10 min
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 600.0


def enabled() -> bool:
    return _ttl_seconds() > 0


def make_key(*parts: Any) -> str:
    """Stable hash over arbitrary parts (strings, dicts, …)."""
    blob = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fingerprint(obj: Any) -> str:
    """Short fingerprint of a (potentially large) object — e.g. an ES mapping."""
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def get(key: str) -> Any | None:
    entry = _store.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.time() > expires_at:
        _store.pop(key, None)
        return None
    _store.move_to_end(key)
    return value


def set(key: str, value: Any, ttl: float | None = None) -> None:  # noqa: A001
    """Store value with `ttl` seconds (default: RST_DSL_CACHE_TTL_S). ttl<=0 → no-op.

    The global kill-switch (RST_DSL_CACHE_TTL_S=0) always wins: callers passing an
    explicit ttl (e.g. field_dict's own TTL) still get vetoed when caching is
    globally disabled, so one switch can turn off all caching.
    """
    if not enabled():
        return
    effective = _ttl_seconds() if ttl is None else ttl
    if effective <= 0:
        return
    _store[key] = (time.time() + effective, value)
    _store.move_to_end(key)
    while len(_store) > _MAX_ENTRIES:
        _store.popitem(last=False)


def clear() -> None:
    _store.clear()
