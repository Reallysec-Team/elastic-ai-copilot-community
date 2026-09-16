"""SIEM backend adapter abstraction (Round 9-C / Phase 0).

The Copilot currently speaks Elasticsearch DSL. To open a path for other
SIEM platforms (Splunk SPL, Azure Sentinel KQL, Wazuh) without committing to
a "universal" abstraction prematurely, we put one indirection in:

    BackendAdapter
        ├─ ElasticAdapter   (✅ ships today — wraps es_client.py)
        ├─ SplunkAdapter    (placeholder — raises NotImplementedError)
        ├─ SentinelAdapter  (placeholder)
        └─ WazuhAdapter     (placeholder)

Each adapter owns:
  * Its own connection client (ES / Splunk REST / Azure Monitor / Wazuh API)
  * Its own LLM system prompt (DSL syntax differs per platform)
  * Its own "list sources" / "get schema" / "execute" semantics

`get_adapter()` returns the active one based on `settings.engine`. Most
existing code keeps calling `es_client.get_es()` directly for now —
adapter is consulted only at decision points (prompt selection, source
listing). Migration to fully adapter-routed calls is intentional future
work, NOT this round.

The abstraction MAY change shape once we actually try Splunk; treat this
as the "place the seam" round, not the "freeze the API" round.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from . import settings as gw_settings


# Engines we know about. UI sees these in the picker — only "elastic" is
# operational today; the rest show as "联系销售解锁" (locked).
ENGINES = ("elastic", "splunk", "sentinel", "wazuh")
ENGINE_LABELS: dict[str, str] = {
    "elastic": "Elasticsearch + Kibana",
    "splunk": "Splunk Enterprise",
    "sentinel": "Azure Sentinel",
    "wazuh": "Wazuh",
}
ENGINE_STATUS: dict[str, str] = {
    "elastic": "available",   # ✅ shipped
    "splunk": "coming_soon",  # adapter pending
    "sentinel": "coming_soon",
    "wazuh": "coming_soon",
}


@runtime_checkable
class BackendAdapter(Protocol):
    """Read-only abstraction across SIEM-like log backends."""

    engine: str
    """One of `ENGINES`. Identifies the adapter type."""

    query_language: str
    """Token used by the UI to label the generated query: 'es_dsl' / 'spl' / 'kql' / 'wazuh'."""

    async def health(self) -> dict[str, Any]:
        """Liveness/readiness check for the underlying engine."""
        ...

    async def list_sources(self) -> list[dict[str, Any]]:
        """Return queryable targets (indices / data streams / saved searches)."""
        ...


# ─────────────────────────── ElasticAdapter ───────────────────────────


class ElasticAdapter:
    engine = "elastic"
    query_language = "es_dsl"

    async def health(self) -> dict[str, Any]:
        from .es_client import get_es
        es = get_es()
        try:
            ok = await es.ping()
        except Exception:
            ok = False
        return {"engine": self.engine, "ok": ok}

    async def list_sources(self) -> list[dict[str, Any]]:
        # Real implementation lives in main.py's /api/indices route — kept
        # there to avoid duplicating cat.indices + resolve_index logic.
        # For Phase 0 this method is unused; we keep it for shape parity
        # with future adapters.
        return []


# ─────────────────────────── placeholders ─────────────────────────────


class _NotImplementedAdapter:
    """Returned for engines whose real implementation hasn't shipped yet."""

    def __init__(self, engine: str) -> None:
        self.engine = engine
        self.query_language = {
            "splunk": "spl",
            "sentinel": "kql",
            "wazuh": "wazuh_rule",
        }.get(engine, "unknown")

    async def health(self) -> dict[str, Any]:
        return {"engine": self.engine, "ok": False, "reason": "adapter not implemented"}

    async def list_sources(self) -> list[dict[str, Any]]:
        return []


# ─────────────────────────── factory ──────────────────────────────────


_singleton: BackendAdapter | None = None
_singleton_engine: str | None = None


def get_adapter() -> BackendAdapter:
    """Return the configured adapter. Cached until settings change."""
    global _singleton, _singleton_engine
    engine = (gw_settings.snapshot(mask_sensitive=False).get("engine") or "elastic").strip().lower()
    if engine not in ENGINES:
        engine = "elastic"
    if _singleton is not None and _singleton_engine == engine:
        return _singleton
    if engine == "elastic":
        _singleton = ElasticAdapter()
    else:
        _singleton = _NotImplementedAdapter(engine)
    _singleton_engine = engine
    return _singleton


def reset() -> None:
    """Force adapter reload — call after settings.engine changes."""
    global _singleton, _singleton_engine
    _singleton = None
    _singleton_engine = None
