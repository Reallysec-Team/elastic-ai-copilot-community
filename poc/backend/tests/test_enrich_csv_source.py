"""CSV source adapter — host/user stable-key hit=high, IP hit=medium, miss=None."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.enrich.entity import Entity  # noqa: E402
from backend.enrich.sources import csv_source  # noqa: E402


class FakeES:
    """Returns a canned hits list; records the last query for assertions."""
    def __init__(self, hits):
        self._hits = hits
        self.last_index = None
        self.last_body = None

    async def search(self, index=None, body=None):
        self.last_index, self.last_body = index, body
        return {"hits": {"hits": self._hits}}


def _hit(src):
    return {"_id": "x", "_source": src}


@pytest.mark.asyncio
async def test_host_hit_is_high_confidence():
    es = FakeES([_hit({"name": "财务DB-01", "criticality": "high",
                       "category": "db", "owner": "张三", "department": "财务部"})])
    ctx = await csv_source.lookup(Entity("host", ("win-db01",), "WIN-DB01"), es)
    assert ctx is not None
    assert ctx["business_name"] == "财务DB-01"
    assert ctx["confidence"] == "high"
    assert ctx["source"] == "csv"
    assert ctx["candidates"] == 1
    assert es.last_index == csv_source.ASSETS_INDEX


@pytest.mark.asyncio
async def test_terms_query_targets_keyword_subfield():
    # Regression: `terms` must hit the un-analyzed `.keyword` subfield. Against the
    # analyzed `text` field a FQDN host key is tokenized and never matches (found
    # in live smoke — every host lookup silently missed).
    for kind, keys in (("host", ("win-db01",)), ("user", ("jsmith",)), ("ip", ("10.0.0.1",))):
        es = FakeES([_hit({"name": "x"})])
        await csv_source.lookup(Entity(kind, keys, keys[0]), es)
        queried_field = next(iter(es.last_body["query"]["terms"]))
        assert queried_field.endswith(".keyword"), f"{kind} queried {queried_field}"


@pytest.mark.asyncio
async def test_ip_hit_is_medium_confidence():
    es = FakeES([_hit({"name": "财务DB-01", "criticality": "high"})])
    ctx = await csv_source.lookup(Entity("ip", ("203.0.113.5",), "203.0.113.5"), es)
    assert ctx["confidence"] == "medium"


@pytest.mark.asyncio
async def test_user_queries_identities_index():
    es = FakeES([_hit({"name": "张三", "department": "财务部"})])
    ctx = await csv_source.lookup(Entity("user", ("jsmith",), "jsmith"), es)
    assert es.last_index == csv_source.IDENTITIES_INDEX
    assert ctx["confidence"] == "high"


@pytest.mark.asyncio
async def test_miss_returns_none():
    ctx = await csv_source.lookup(Entity("host", ("nope",), "nope"), FakeES([]))
    assert ctx is None


@pytest.mark.asyncio
async def test_multiple_candidates_counted():
    es = FakeES([_hit({"name": "A"}), _hit({"name": "B"})])
    ctx = await csv_source.lookup(Entity("ip", ("10.0.0.1",), "10.0.0.1"), es)
    assert ctx["candidates"] == 2
    assert ctx["business_name"] == "A"  # first is best


@pytest.mark.asyncio
async def test_es_error_returns_none():
    class Boom:
        async def search(self, index=None, body=None):
            raise RuntimeError("es down")
    ctx = await csv_source.lookup(Entity("host", ("h",), "h"), Boom())
    assert ctx is None


@pytest.mark.asyncio
async def test_malformed_response_returns_none():
    class Weird:
        async def search(self, index=None, body=None):
            return object()  # no .get, no .body
    ctx = await csv_source.lookup(Entity("host", ("h",), "h"), Weird())
    assert ctx is None
