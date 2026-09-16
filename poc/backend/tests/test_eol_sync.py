"""eol_sync 脚本纯 helper 单测（URL 拼装 / 产品解析）。fetch 出网部分不单测（纯边界）。"""
from __future__ import annotations

import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from scripts import eol_sync  # noqa: E402
from backend.baseline import eol_catalog  # noqa: E402


def test_api_url_joins_product():
    assert eol_sync.api_url("https://endoflife.date/api", "centos") == "https://endoflife.date/api/centos.json"


def test_api_url_strips_trailing_slash():
    assert eol_sync.api_url("http://mirror/eol/", "ubuntu") == "http://mirror/eol/ubuntu.json"


def test_parse_products_comma_list():
    assert eol_sync.parse_products("centos, ubuntu ,debian") == ["centos", "ubuntu", "debian"]


def test_parse_products_default_when_empty():
    assert eol_sync.parse_products(None) == list(eol_catalog.DEFAULT_PRODUCTS)
    assert eol_sync.parse_products("") == list(eol_catalog.DEFAULT_PRODUCTS)


def test_offline_run_never_touches_network(monkeypatch):
    """离线核心保证：--offline 不出网、不写库，仅报告现有缓存，退出 0。"""
    import asyncio

    calls = {"count": 0, "closed": False}

    async def _count():
        calls["count"] += 1
        return 7

    async def _close():
        calls["closed"] = True

    def _no_httpx(*a, **k):
        raise AssertionError("离线路径不该导入/调用 httpx")

    monkeypatch.setattr(eol_sync.eol_store, "count", _count)
    monkeypatch.setattr(eol_sync, "close_es", _close)
    monkeypatch.setattr(eol_sync.eol_store, "bulk_upsert", _no_httpx)

    rc = asyncio.run(eol_sync._run(["centos"], eol_sync.DEFAULT_BASE_URL, offline=True, timeout=1.0))
    assert rc == 0
    assert calls["count"] == 1
    assert calls["closed"] is True
