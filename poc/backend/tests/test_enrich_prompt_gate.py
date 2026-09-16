"""Masking-mode egress gate — cloud SKIPS prompt injection; private/airgapped
inject the resolved asset block."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.enrich import prompt_context, resolver  # noqa: E402


class FakeES:
    async def search(self, index=None, body=None):
        if ".rst_copilot_assets" in index:
            # Only return results if searching for "win-db01", not "ghost".
            # Field-name-agnostic: csv_source queries the `.keyword` subfield, so
            # match on the terms VALUES, not a hardcoded field key.
            if body and "query" in body and "terms" in body["query"]:
                vals = next(iter(body["query"]["terms"].values()), [])
                if "win-db01" in vals:
                    return {"hits": {"hits": [{"_source": {"name": "财务DB-01",
                            "criticality": "high", "owner": "张三", "department": "财务部"}}]}}
        return {"hits": {"hits": []}}


@pytest.fixture(autouse=True)
def _clear():
    resolver.clear_cache()
    yield
    resolver.clear_cache()


@pytest.mark.asyncio
async def test_cloud_mode_skips_injection(monkeypatch):
    monkeypatch.setenv("RST_MASKING_MODE", "cloud")
    block = await prompt_context.asset_context_block({"host.name": "win-db01"}, FakeES())
    assert block is None


@pytest.mark.asyncio
async def test_private_mode_injects(monkeypatch):
    monkeypatch.setenv("RST_MASKING_MODE", "private")
    block = await prompt_context.asset_context_block({"host.name": "win-db01"}, FakeES())
    assert block is not None
    assert "财务DB-01" in block
    assert "张三" in block


@pytest.mark.asyncio
async def test_airgapped_mode_injects(monkeypatch):
    monkeypatch.setenv("RST_MASKING_MODE", "airgapped")
    block = await prompt_context.asset_context_block({"host.name": "win-db01"}, FakeES())
    assert block is not None


@pytest.mark.asyncio
async def test_private_unresolved_returns_none(monkeypatch):
    monkeypatch.setenv("RST_MASKING_MODE", "private")
    block = await prompt_context.asset_context_block({"host.name": "ghost"}, FakeES())
    assert block is None


def test_format_block_includes_source_and_confidence():
    ctx = {"business_name": "财务DB-01", "criticality": "high", "category": "db",
           "owner": "张三", "department": "财务部", "source": "csv",
           "confidence": "high", "candidates": 1}
    s = prompt_context.format_block(ctx)
    assert "csv" in s and "high" in s and "财务DB-01" in s
