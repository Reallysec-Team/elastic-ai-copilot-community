"""Direct read of enrich-processor富化 fields already stamped on the alert doc
(0 ES query). Customer configures an enrich processor → alert carries
rst.asset.* fields → we read them straight off `raw`."""

from __future__ import annotations

from typing import Any

from ..entity import AssetContext
from ...alerts.store import dig


def from_doc(raw: dict[str, Any]) -> AssetContext | None:
    name = dig(raw, "rst.asset.name")
    if not name:
        return None
    return {
        "business_name": str(name),
        "criticality": dig(raw, "rst.asset.criticality"),
        "category": dig(raw, "rst.asset.category"),
        "owner": dig(raw, "rst.asset.owner"),
        "department": dig(raw, "rst.asset.department"),
        "source": "enrich",
        "confidence": "high",
        "candidates": 1,
    }
