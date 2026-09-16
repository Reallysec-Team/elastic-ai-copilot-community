import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import report_agg  # noqa: E402


class FakeEntityES:
    def __init__(self, hit=None, boom=False):
        self._hit = hit
        self._boom = boom
        self.queried_fields = []

    async def search(self, index=None, body=None):
        if self._boom:
            raise RuntimeError("es down")
        self.queried_fields.append(next(iter(body["query"]["terms"].keys())))
        hits = [{"_source": {"asset": self._hit}}] if self._hit else []
        return type("R", (), {"body": {"hits": {"hits": hits}}})()


@pytest.mark.asyncio
async def test_enrich_host_hit_merges_asset_fields():
    es = FakeEntityES(hit={"name": "核心数据库", "criticality": "high", "owner": "dba"})
    out = await report_agg.enrich_entities(es, [{"value": "WIN-DB01", "field": "host.name", "count": 9}])
    assert out[0]["business_name"] == "核心数据库"
    assert out[0]["criticality"] == "high"
    assert out[0]["owner"] == "dba"
    assert es.queried_fields == ["host.name"]


@pytest.mark.asyncio
async def test_enrich_ip_entity_is_skipped_no_lookup():
    es = FakeEntityES(hit={"name": "should-not-be-used"})
    out = await report_agg.enrich_entities(es, [{"value": "10.0.0.5", "field": "source.ip", "count": 4}])
    assert out[0]["business_name"] is None
    assert out[0]["criticality"] is None
    assert es.queried_fields == []  # ip never queried


@pytest.mark.asyncio
async def test_enrich_miss_and_error_yield_none():
    miss = await report_agg.enrich_entities(FakeEntityES(hit=None),
                                            [{"value": "H", "field": "host.name", "count": 1}])
    assert miss[0]["business_name"] is None
    boom = await report_agg.enrich_entities(FakeEntityES(boom=True),
                                            [{"value": "H", "field": "host.name", "count": 1}])
    assert boom[0]["business_name"] is None and boom[0]["owner"] is None
