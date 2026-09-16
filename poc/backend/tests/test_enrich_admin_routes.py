"""Admin CSV upload handlers — admin-gated, delegate to csv_import; probe status."""
import os
import sys
from pathlib import Path

import pytest

os.environ.pop("RST_ADMIN_TOKEN", None)  # dev mode → require_admin passes
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import main  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class FakeReq:
    headers: dict = {}

    async def json(self):
        return {"csv": "name,host\n财务DB-01,win-db01\n"}


class FakeES:
    async def bulk(self, operations=None, **kw):
        return {"errors": False}


@pytest.mark.asyncio
async def test_assets_upload(monkeypatch):
    monkeypatch.setattr(main, "get_es", lambda: FakeES())
    out = await main.admin_enrichment_assets(FakeReq())
    assert out["indexed"] == 1


@pytest.mark.asyncio
async def test_bad_csv_400(monkeypatch):
    monkeypatch.setattr(main, "get_es", lambda: FakeES())

    class BadReq(FakeReq):
        async def json(self):
            return {"csv": "name,evil\na,b\n"}

    with pytest.raises(HTTPException) as e:
        await main.admin_enrichment_assets(BadReq())
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_non_dict_body_400(monkeypatch):
    monkeypatch.setattr(main, "get_es", lambda: FakeES())

    class ListReq(FakeReq):
        async def json(self):
            return [1, 2, 3]

    with pytest.raises(HTTPException) as e:
        await main.admin_enrichment_assets(ListReq())
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_status_route():
    out = await main.admin_enrichment_status(FakeReq())
    assert "csv" in out["sources"]
