"""CSV-backed lookup — the保底 source. Assets keyed by normalized host keys / IP
in .rst_copilot_assets; identities keyed by normalized user in
.rst_copilot_identities. Stable-key (host/user) hit → high confidence; IP hit →
medium (current value, may drift). Any ES error → None (resolver顺延)."""

from __future__ import annotations

import logging
from typing import Any

from ..entity import AssetContext, Entity

logger = logging.getLogger("rst.enrich.csv_source")

ASSETS_INDEX = ".rst_copilot_assets"
IDENTITIES_INDEX = ".rst_copilot_identities"

# CSV columns projected into an AssetContext.
_FIELDS = ("criticality", "category", "owner", "department")


async def lookup(entity: Entity, es) -> AssetContext | None:
    if entity.kind == "user":
        index, field, confidence = IDENTITIES_INDEX, "user_key", "high"
    elif entity.kind == "host":
        index, field, confidence = ASSETS_INDEX, "keys", "high"
    else:  # ip
        index, field, confidence = ASSETS_INDEX, "ip", "medium"

    # Query the `.keyword` subfield, not the base field. CSV import relies on
    # ES dynamic mapping, which makes these join columns `text` (analyzed) with a
    # `.keyword` subfield. `terms` needs an exact, un-analyzed match — against the
    # analyzed `text` field a host like "win-db01.corp.local" is tokenized and
    # never matches, so every host/user lookup silently missed.
    # ponytail: `.keyword` has ignore_above:256; host/user/ip join keys are far
    # shorter, so no key is dropped. Explicit keyword mapping is the phase-2 fix.
    body = {"size": 5, "query": {"terms": {f"{field}.keyword": list(entity.keys)}}}
    try:
        resp = await es.search(index=index, body=body)
        body_out = getattr(resp, "body", resp)
        hits = ((body_out.get("hits") or {}).get("hits")) or []
    except Exception as e:  # noqa: BLE001 — any failure顺延
        logger.debug("csv_source lookup failed on %s: %s", index, e)
        return None
    if not hits:
        return None
    src: dict[str, Any] = hits[0].get("_source") or {}
    ctx: AssetContext = {
        "business_name": src.get("name"),
        "source": "csv",
        "confidence": confidence,
        "candidates": len(hits),
    }
    for f in _FIELDS:
        ctx[f] = src.get(f)  # type: ignore[literal-required]
    return ctx
