"""Resolver gradient chain: enrich→entity_store→criticality→csv→None, host/user
before IP, TTL cache, ambiguity candidates."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.enrich import resolver  # noqa: E402


class FakeES:
    """Maps index-substring → canned hits; counts searches for cache assertions."""
    def __init__(self, table):
        self.table = table  # list[(index_substr, hits)]
        self.calls = 0

    async def search(self, index=None, body=None):
        self.calls += 1
        for sub, hits in self.table:
            if sub in index:
                return {"hits": {"hits": hits}}
        return {"hits": {"hits": []}}


def _hit(src):
    return {"_id": "x", "_source": src}


@pytest.fixture(autouse=True)
def _clear():
    resolver.clear_cache()
    yield
    resolver.clear_cache()


@pytest.mark.asyncio
async def test_enrich_wins_with_zero_es_calls():
    es = FakeES([])
    raw = {"host.name": "win-db01", "rst.asset.name": "财务DB-01"}
    ctx = await resolver.resolve(raw, es)
    assert ctx["source"] == "enrich"
    assert es.calls == 0


@pytest.mark.asyncio
async def test_falls_through_to_csv():
    es = FakeES([(".rst_copilot_assets", [_hit({"name": "财务DB-01", "criticality": "high"})])])
    raw = {"host.name": "WIN-DB01.corp.local"}
    ctx = await resolver.resolve(raw, es)
    assert ctx["source"] == "csv"
    assert ctx["confidence"] == "high"


@pytest.mark.asyncio
async def test_host_tried_before_ip():
    # host misses everywhere, ip hits csv → ip result only because host exhausted
    es = FakeES([(".rst_copilot_assets", [])])
    raw = {"host.name": "ghost", "source.ip": "203.0.113.5"}
    # assets index returns [] for both host terms and ip terms in this fake, so → None
    ctx = await resolver.resolve(raw, es)
    assert ctx is None


@pytest.mark.asyncio
async def test_all_miss_returns_none():
    ctx = await resolver.resolve({"host.name": "nope"}, FakeES([]))
    assert ctx is None


@pytest.mark.asyncio
async def test_cache_hit_avoids_second_lookup():
    es = FakeES([(".rst_copilot_assets", [_hit({"name": "A"})])])
    raw = {"host.name": "win-db01"}
    await resolver.resolve(raw, es, now=1000.0)
    first = es.calls
    await resolver.resolve(raw, es, now=1100.0)  # within TTL
    assert es.calls == first  # served from cache


@pytest.mark.asyncio
async def test_cache_expires_after_ttl():
    es = FakeES([(".rst_copilot_assets", [_hit({"name": "A"})])])
    raw = {"host.name": "win-db01"}
    await resolver.resolve(raw, es, now=1000.0)
    first = es.calls
    await resolver.resolve(raw, es, now=1000.0 + resolver._TTL_SECONDS + 1)
    assert es.calls > first  # re-queried after expiry


@pytest.mark.asyncio
async def test_ambiguous_ip_reports_candidates():
    es = FakeES([(".rst_copilot_assets", [_hit({"name": "A"}), _hit({"name": "B"})])])
    ctx = await resolver.resolve({"source.ip": "10.0.0.1"}, es)
    assert ctx["candidates"] == 2
    assert ctx["confidence"] == "medium"


@pytest.mark.asyncio
async def test_negative_cached_host_skips_to_ip():
    # host misses all sources; ip hits csv. Verify that negatively-cached host
    # is skipped on the second resolve (not treated as a hard stop), and ip context
    # is still returned.
    class HostMissIpHit:
        def __init__(self):
            self.calls = 0

        async def search(self, index=None, body=None):
            self.calls += 1
            # csv assets index: return a hit only when the query is the ip term
            if ".rst_copilot_assets" in index:
                terms = (((body or {}).get("query") or {}).get("terms") or {})
                vals = next(iter(terms.values()), [])
                if "203.0.113.5" in vals:
                    return {"hits": {"hits": [_hit({"name": "财务DB-01", "criticality": "high"})]}}
            return {"hits": {"hits": []}}

    es = HostMissIpHit()
    raw = {"host.name": "ghost", "source.ip": "203.0.113.5"}
    # First resolve: host misses, ip hits → context with source='csv'
    ctx1 = await resolver.resolve(raw, es, now=1000.0)
    assert ctx1 is not None and ctx1["source"] == "csv" and ctx1["confidence"] == "medium"
    # Second resolve within TTL: host negative-cache hit must be skipped, ip re-resolved
    ctx2 = await resolver.resolve(raw, es, now=1100.0)
    assert ctx2 is not None and ctx2["confidence"] == "medium"


@pytest.mark.asyncio
async def test_cache_is_capped_and_drops_the_coldest_entry(monkeypatch):
    """缓存的键是实体值本身（每一个见过的 IP / 主机 / 账号），TTL 只在读的时候看。

    没有上限的话，见过一次再也不会出现的实体会永远占着位置 —— 在一个长期运行的
    容器里那不是缓存，是只涨不跌。这条钉住「到顶就淘汰最久没用的那条」。
    """
    monkeypatch.setattr(resolver, "_MAX_ENTRIES", 3)
    es = FakeES([(".rst_copilot_assets", [_hit({"name": "A"})])])

    for i in range(3):
        await resolver.resolve({"host.name": f"h{i}"}, es, now=1000.0)
    assert len(resolver._cache) == 3

    # 再命中一次最早写进去的那条：它现在是最新用过的，不该是下一个被淘汰的。
    await resolver.resolve({"host.name": "h0"}, es, now=1100.0)
    await resolver.resolve({"host.name": "h3"}, es, now=1100.0)

    keys = "|".join(resolver._cache)
    assert len(resolver._cache) == 3
    assert "h0" in keys and "h3" in keys
    assert "h1" not in keys  # 最久没用的那条走了
