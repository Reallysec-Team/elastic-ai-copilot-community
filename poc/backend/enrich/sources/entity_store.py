"""Best-effort Elastic Entity Store lookup (.entities.v1.latest.*). MVP maps only
the obvious name/criticality fields; deep field mapping is phase 2. Any miss or
error → None so the resolver顺延 to the next source."""

from __future__ import annotations

import logging

from ..entity import AssetContext, Entity

logger = logging.getLogger("rst.enrich.entity_store")

_INDEX = ".entities.v1.latest.security_*"


async def lookup(entity: Entity, es) -> AssetContext | None:
    # Entity Store keys hosts/users by name; MVP only resolves those two.
    if entity.kind == "ip":
        return None
    field = "host.name" if entity.kind == "host" else "user.name"
    body = {"size": 1, "query": {"terms": {field: list(entity.keys)}}}
    try:
        resp = await es.search(index=_INDEX, body=body)
    except Exception as e:  # noqa: BLE001 — best-effort, silently顺延
        logger.debug("entity_store lookup failed: %s", e)
        return None
    body_out = getattr(resp, "body", resp)
    hits = ((body_out.get("hits") or {}).get("hits")) or []
    if not hits:
        return None
    asset = (hits[0].get("_source") or {}).get("asset") or {}
    if not asset.get("name"):
        return None
    return {
        "business_name": asset.get("name"),
        "criticality": asset.get("criticality"),
        "category": asset.get("category"),
        "owner": asset.get("owner"),
        "department": asset.get("department"),
        "source": "entity_store",
        "confidence": "high",
        "candidates": 1,
    }
