"""Enrichment endpoint — resolves the stored alert's entities, unmasked. Uses
the route handler directly (no ASGI) to avoid a live ES / middleware."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import alerts_routes  # noqa: E402
from backend.enrich import resolver  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class FakeES:
    """Canned hit only for host key "win-db01" — mirrors test_enrich_resolver.py's
    table-driven fake so the "ghost" case genuinely misses instead of matching
    a fake that ignores query terms."""
    async def search(self, index=None, body=None):
        if ".rst_copilot_assets" in index:
            terms = (((body or {}).get("query") or {}).get("terms") or {})
            keys = next(iter(terms.values()), [])
            if "win-db01" in keys:
                return {"hits": {"hits": [{"_source": {"name": "财务DB-01", "criticality": "high"}}]}}
        return {"hits": {"hits": []}}


@pytest.fixture(autouse=True)
def _clear():
    resolver.clear_cache()
    yield
    resolver.clear_cache()


@pytest.mark.asyncio
async def test_hit_returns_context(monkeypatch):
    async def fake_get_alert(aid):
        return {"alert_id": aid, "raw": {"host.name": "win-db01"}}
    monkeypatch.setattr(alerts_routes.store, "get_alert", fake_get_alert)
    monkeypatch.setattr(alerts_routes, "get_es", lambda: FakeES())
    out = await alerts_routes.alert_enrichment("a1")
    assert out["enrichment"]["business_name"] == "财务DB-01"


@pytest.mark.asyncio
async def test_miss_returns_null(monkeypatch):
    async def fake_get_alert(aid):
        return {"alert_id": aid, "raw": {"host.name": "ghost"}}
    monkeypatch.setattr(alerts_routes.store, "get_alert", fake_get_alert)
    monkeypatch.setattr(alerts_routes, "get_es", lambda: FakeES())
    out = await alerts_routes.alert_enrichment("a1")
    assert out["enrichment"] is None


@pytest.mark.asyncio
async def test_missing_alert_404(monkeypatch):
    async def fake_get_alert(aid):
        return None
    monkeypatch.setattr(alerts_routes.store, "get_alert", fake_get_alert)
    with pytest.raises(HTTPException) as e:
        await alerts_routes.alert_enrichment("nope")
    assert e.value.status_code == 404
