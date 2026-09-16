"""enrich (0-query direct read), entity_store + criticality (best-effort)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.enrich.entity import Entity  # noqa: E402
from backend.enrich.sources import criticality, enrich_source, entity_store  # noqa: E402


class FakeES:
    def __init__(self, hits):
        self._hits = hits

    async def search(self, index=None, body=None):
        return {"hits": {"hits": self._hits}}


def test_enrich_reads_flattened_fields():
    raw = {"rst.asset.name": "财务DB-01", "rst.asset.criticality": "high"}
    ctx = enrich_source.from_doc(raw)
    assert ctx["business_name"] == "财务DB-01"
    assert ctx["source"] == "enrich"
    assert ctx["confidence"] == "high"


def test_enrich_none_when_absent():
    assert enrich_source.from_doc({"message": "x"}) is None


@pytest.mark.asyncio
async def test_entity_store_hit():
    hit = {"_source": {"asset": {"name": "财务DB-01", "criticality": "high"}}}
    ctx = await entity_store.lookup(Entity("host", ("win-db01",), "WIN-DB01"), FakeES([hit]))
    assert ctx["business_name"] == "财务DB-01"
    assert ctx["source"] == "entity_store"


@pytest.mark.asyncio
async def test_entity_store_miss_returns_none():
    assert await entity_store.lookup(Entity("host", ("h",), "h"), FakeES([])) is None


@pytest.mark.asyncio
async def test_entity_store_error_returns_none():
    class Boom:
        async def search(self, index=None, body=None):
            raise RuntimeError("no such index")
    assert await entity_store.lookup(Entity("host", ("h",), "h"), Boom()) is None


@pytest.mark.asyncio
async def test_criticality_hit():
    hit = {"_source": {"criticality_level": "high_impact"}}
    ctx = await criticality.lookup(Entity("host", ("win-db01",), "WIN-DB01"), FakeES([hit]))
    assert ctx["criticality"] == "high_impact"
    assert ctx["source"] == "criticality"


@pytest.mark.asyncio
async def test_criticality_error_returns_none():
    class Boom:
        async def search(self, index=None, body=None):
            raise RuntimeError("down")
    assert await criticality.lookup(Entity("host", ("h",), "h"), Boom()) is None
