"""Capability probe — best-effort index existence; csv always available."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.enrich import probe  # noqa: E402


class FakeIndices:
    def __init__(self, existing):
        self._existing = existing

    async def exists(self, index=None):
        return any(sub in index for sub in self._existing)


class FakeES:
    def __init__(self, existing):
        self.indices = FakeIndices(existing)


@pytest.mark.asyncio
async def test_probe_detects_present_sources():
    r = await probe.run(FakeES([".entities.v1.latest"]))
    assert r["entity_store"] is True
    assert r["criticality"] is False
    assert r["csv"] is True


@pytest.mark.asyncio
async def test_probe_all_absent():
    r = await probe.run(FakeES([]))
    assert r["entity_store"] is False
    assert r["criticality"] is False
    assert r["csv"] is True


@pytest.mark.asyncio
async def test_status_reflects_last_run():
    await probe.run(FakeES([".asset-criticality"]))
    assert probe.status()["criticality"] is True


@pytest.mark.asyncio
async def test_probe_error_degrades_to_false():
    class Boom:
        class indices:
            @staticmethod
            async def exists(index=None):
                raise RuntimeError("es down")
    r = await probe.run(Boom())
    assert r["entity_store"] is False
    assert r["csv"] is True  # 保底 unaffected
