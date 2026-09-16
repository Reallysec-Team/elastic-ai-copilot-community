"""Best-effort Asset Criticality lookup. MVP surfaces only the criticality level;
any miss/error → None. Deep mapping is phase 2."""

from __future__ import annotations

import logging

from ..entity import AssetContext, Entity

logger = logging.getLogger("rst.enrich.criticality")

_INDEX = ".asset-criticality.asset-criticality-*"


async def lookup(entity: Entity, es) -> AssetContext | None:
    if entity.kind == "ip":
        return None
    field = "host.name" if entity.kind == "host" else "user.name"
    body = {"size": 1, "query": {"terms": {field: list(entity.keys)}}}
    try:
        resp = await es.search(index=_INDEX, body=body)
    except Exception as e:  # noqa: BLE001
        logger.debug("criticality lookup failed: %s", e)
        return None
    body_out = getattr(resp, "body", resp)
    hits = ((body_out.get("hits") or {}).get("hits")) or []
    if not hits:
        return None
    level = (hits[0].get("_source") or {}).get("criticality_level")
    if not level:
        return None
    return {
        "business_name": None,
        "criticality": level,
        "source": "criticality",
        "confidence": "high",
        "candidates": 1,
    }
