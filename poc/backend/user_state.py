"""Server-side per-owner state store, backed by Elasticsearch.

Gives the UI durable, cross-device (and, for shared kinds, cross-analyst) state
that previously lived only in each browser's localStorage:

  - triage cluster disposition (已处置 / 误报 / 升级) — TEAM-shared so a mark by
    one analyst is visible to the whole shift
  - persisted triage runs
  - query history, UI preferences (columns / default index / page size)
  - named saved queries

Document model (one doc per (owner, kind, key)):
    _id        = "{owner}::{kind}::{key}"   ← deterministic, so PUT is an upsert
    owner      keyword   — SSO username, or "_shared" (no SSO), or "_team"
    kind       keyword   — one of ALLOWED_KINDS
    key        keyword   — caller-chosen id (cluster_id / query id / "ui" / ...)
    value_json keyword(index:false) — the value, JSON-encoded (any shape)
    updated_at date
    updated_by keyword   — who last wrote it (for shared kinds' attribution)

Writing requires the gateway's ES connection to have WRITE on this index. Like
audit, this trades the "read-only on customer ES" default for the feature; the
endpoints surface a friendly error if the write is refused, and the frontend
falls back to localStorage so single-box / read-only deployments still work.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from .es_client import get_es

logger = logging.getLogger("rst.user_state")

DEFAULT_INDEX = ".rst_copilot_userstate"

# Personal state is keyed to the SSO user (or "_shared" without SSO). Shared
# state is keyed to "_team" so the whole shift sees the same thing.
PERSONAL_KINDS = {"pref", "history", "saved_query"}
# Team-shared. A disposition or a saved rule is a shift-level fact: one analyst
# marking an alert as a false positive has to stop the next analyst re-opening
# it, and a rule crafted once should be there for everyone.
SHARED_KINDS = {"triage_status", "triage_result", "detection_rule", "alert_status"}
ALLOWED_KINDS = PERSONAL_KINDS | SHARED_KINDS

_SHARED_OWNER = "_team"
_ANON_OWNER = "_shared"

_MAPPING: dict[str, Any] = {
    "mappings": {
        "properties": {
            "owner": {"type": "keyword"},
            "kind": {"type": "keyword"},
            "key": {"type": "keyword"},
            "value_json": {"type": "keyword", "index": False, "doc_values": False},
            "updated_at": {"type": "date"},
            "updated_by": {"type": "keyword"},
        }
    }
}

_ensured = False
_ensure_lock = asyncio.Lock()


def _index_name() -> str:
    return os.environ.get("RST_USERSTATE_INDEX", DEFAULT_INDEX).strip() or DEFAULT_INDEX


def owner_for(kind: str, user: dict[str, Any] | None) -> str:
    """Resolve the storage owner for a kind: shared kinds → the team bucket;
    personal kinds → the SSO username, or the anonymous bucket without SSO."""
    if kind in SHARED_KINDS:
        return _SHARED_OWNER
    name = (user or {}).get("username") if user else None
    return str(name) if name else _ANON_OWNER


def _doc_id(owner: str, kind: str, key: str) -> str:
    return f"{owner}::{kind}::{key}"


def _shared_fallback_enabled() -> bool:
    """The dual-read period. Set RST_SHARED_BUCKET_FALLBACK=0 to end it."""
    return os.environ.get("RST_SHARED_BUCKET_FALLBACK", "").strip().lower() not in {
        "0", "false", "no",
    }


def read_owners(owner: str, kind: str) -> list[str]:
    """Owners to read for `owner`, newest bucket first.

    Everything written before identity existed under password login sits in
    `_shared`, because `current_user()` returned None and there was no name to
    file it under. Now that there is one, writes go to the named bucket — and
    if reads went only there, an existing deployment's history, prefs and saved
    queries would appear to vanish on the day it upgrades.

    So the first administrator also reads `_shared`: it is the account those
    documents were actually created by, the only one that existed. Nobody else
    inherits them, and writes never go back — each key migrates the first time
    it is touched.

    "First administrator" rather than "the configured account" because there is
    a user table now and the configured account is only its seed. On a
    deployment that upgraded, the two are the same name; on one that started
    fresh there is nothing in `_shared` to inherit either way.
    """
    if kind in SHARED_KINDS or owner == _ANON_OWNER or not _shared_fallback_enabled():
        return [owner]
    # Imported here rather than at module scope: user_db pulls in session_auth,
    # which pulls in the request/response types, and this module is imported
    # from the ES layer.
    from .user_db import first_admin

    return [owner, _ANON_OWNER] if owner == first_admin() else [owner]


async def _ensure() -> None:
    global _ensured
    if _ensured:
        return
    async with _ensure_lock:
        if _ensured:
            return
        es = get_es()
        try:
            if not await es.indices.exists(index=_index_name()):
                await es.indices.create(index=_index_name(), body=_MAPPING)
        except Exception as e:  # noqa: BLE001
            # A race (another worker created it first) means the index now exists —
            # that's success, not failure. Anything else (perms, ES down) leaves
            # _ensured unset so the next call retries instead of silently giving up.
            if not _is_already_exists(e):
                logger.warning("userstate_ensure_failed", extra={"error": str(e)})
                return
        _ensured = True


def _is_already_exists(e: Exception) -> bool:
    """True when the index-create failed only because the index already exists
    (lost a create race) — which is functionally a success."""
    # Only treat the error as "already exists" when the message actually says so.
    # A bare `isinstance(e, BadRequestError)` would also swallow genuine 400s
    # (e.g. a bad mapping), wrongly marking the index ensured and hiding the
    # real fault. Those must fail so the next call can retry / surface them.
    text = str(e).lower()
    if "resource_already_exists" in text or "already exists" in text:
        return True
    try:
        from elasticsearch import BadRequestError
        # Some client versions expose the structured error type without the
        # phrase in str(); check the parsed body's error type as well.
        if isinstance(e, BadRequestError):
            info = getattr(e, "info", None) or getattr(e, "body", None)
            err_type = ""
            if isinstance(info, dict):
                err = info.get("error")
                if isinstance(err, dict):
                    err_type = str(err.get("type", "")).lower()
                else:
                    err_type = str(err).lower()
            return "resource_already_exists" in err_type
    except Exception:  # noqa: BLE001
        pass
    return False


async def put(owner: str, kind: str, key: str, value: Any, updated_by: str | None) -> None:
    await _ensure()
    es = get_es()
    body = {
        "owner": owner,
        "kind": kind,
        "key": key,
        "value_json": json.dumps(value, ensure_ascii=False),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": updated_by or None,
    }
    await es.index(index=_index_name(), id=_doc_id(owner, kind, key), document=body, refresh="wait_for")


async def get(owner: str, kind: str, key: str) -> Any | None:
    await _ensure()
    es = get_es()
    from elasticsearch import NotFoundError
    for o in read_owners(owner, kind):
        try:
            resp = await es.get(index=_index_name(), id=_doc_id(o, kind, key))
        except NotFoundError:
            continue
        return _decode(resp.body.get("_source") or {})
    return None


async def delete(owner: str, kind: str, key: str) -> bool:
    await _ensure()
    es = get_es()
    from elasticsearch import NotFoundError
    # Deletes sweep the legacy bucket too. Otherwise removing an inherited
    # saved query would appear to succeed and the item would come straight back
    # on the next read.
    deleted = False
    for o in read_owners(owner, kind):
        try:
            await es.delete(index=_index_name(), id=_doc_id(o, kind, key), refresh="wait_for")
            deleted = True
        except NotFoundError:
            continue
    return deleted


async def list_items(owner: str, kind: str, *, size: int = 1000) -> list[dict[str, Any]]:
    await _ensure()
    es = get_es()
    owners = read_owners(owner, kind)
    dsl = {
        "size": max(1, min(size, 5000)),
        "query": {"bool": {"filter": [{"terms": {"owner": owners}}, {"term": {"kind": kind}}]}},
        "sort": [{"updated_at": {"order": "desc"}}],
    }
    resp = await es.search(index=_index_name(), body=dsl)
    out: list[dict[str, Any]] = []
    # A key already migrated to the named bucket also still exists in the legacy
    # one until it is next written; show it once, and show the newer of the two.
    # Sorted newest-first above, so the first sighting of a key is the one to keep.
    seen: set[str] = set()
    for hit in (resp.body.get("hits") or {}).get("hits") or []:
        src = hit.get("_source") or {}
        k = str(src.get("key"))
        if k in seen:
            continue
        seen.add(k)
        out.append(
            {
                "key": src.get("key"),
                "value": _decode(src),
                "updated_at": src.get("updated_at"),
                "updated_by": src.get("updated_by"),
            }
        )
    return out


def _decode(src: dict[str, Any]) -> Any:
    raw = src.get("value_json")
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None
