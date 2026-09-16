"""Startup capability probe — which enrichment sources exist in the customer
ELK. Best-effort: any error → that source reported absent. CSV is always
available (保底), so enrichment is never blocked by ELK capability."""

from __future__ import annotations

import logging

logger = logging.getLogger("rst.enrich.probe")

_ENTITY_STORE_INDEX = ".entities.v1.latest.security_*"
_CRITICALITY_INDEX = ".asset-criticality.asset-criticality-*"

_state: dict[str, bool] = {"entity_store": False, "criticality": False, "csv": True}


async def _exists(es, index: str) -> bool:
    try:
        return bool(await es.indices.exists(index=index))
    except Exception as e:  # noqa: BLE001 — absent on any error
        logger.debug("probe exists(%s) failed: %s", index, e)
        return False


async def run(es) -> dict[str, bool]:
    _state["entity_store"] = await _exists(es, _ENTITY_STORE_INDEX)
    _state["criticality"] = await _exists(es, _CRITICALITY_INDEX)
    _state["csv"] = True
    logger.info("enrichment_probe", extra={"sources": dict(_state)})
    return dict(_state)


def status() -> dict[str, bool]:
    return dict(_state)
