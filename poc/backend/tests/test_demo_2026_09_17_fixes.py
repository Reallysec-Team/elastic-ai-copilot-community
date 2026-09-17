"""Regressions caught on the aisoc demo box (2026-09-17):

* the report archive index was created by dynamic mapping → ``boundary_key``
  became a date and the weekly ``2026-W38`` doc was rejected with 400;
* an ``llm_providers.yml`` holding only the ``embedding:`` section (what the
  embedding settings page writes) made the router load ZERO chat providers
  after a restart even though LLM_API_KEY / LLM_MODEL were set;
* alert ingest's cold-start window was a fixed ``now-1h``;
* baseline platform detection from ``host.os.*``.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import llm_router, report_scheduler as rs  # noqa: E402
from backend.alerts import ingest  # noqa: E402
from backend.baseline import result_reader  # noqa: E402


# ── reports: explicit mapping, created once ──────────────────────────────────

class _FakeIndices:
    def __init__(self, exists: bool):
        self._exists = exists
        self.created = []

    async def exists(self, index):
        return self._exists

    async def create(self, index, body):
        self.created.append((index, body))


class _FakeES:
    def __init__(self, exists=False):
        self.indices = _FakeIndices(exists)


def test_report_index_is_created_with_keyword_boundary_key(monkeypatch):
    monkeypatch.setattr(rs, "_index_ready", False)
    es = _FakeES(exists=False)
    asyncio.run(rs._ensure_index(es))
    assert len(es.indices.created) == 1
    _, body = es.indices.created[0]
    assert body["mappings"]["properties"]["boundary_key"] == {"type": "keyword"}
    # idempotent: second call does not touch ES again
    asyncio.run(rs._ensure_index(es))
    assert len(es.indices.created) == 1


def test_report_index_left_alone_when_it_exists(monkeypatch):
    monkeypatch.setattr(rs, "_index_ready", False)
    es = _FakeES(exists=True)
    asyncio.run(rs._ensure_index(es))
    assert es.indices.created == []
    assert rs._index_ready is True


# ── llm router: embedding-only file must not hide the env provider ───────────

def test_embedding_only_config_file_falls_back_to_env(tmp_path, monkeypatch):
    cfg = tmp_path / "llm.yml"
    cfg.write_text("embedding:\n  model: doubao-embedding-vision\n  dims: 2048\n", encoding="utf-8")
    monkeypatch.setenv("RST_LLM_CONFIG", str(cfg))
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "ark-code-latest")
    monkeypatch.setenv("LLM_BASE_URL", "https://ark.example/api/coding/v3")
    router = llm_router.load_router()
    assert [p.model for p in router.providers] == ["ark-code-latest"]


def test_explicit_empty_providers_list_still_means_none(tmp_path, monkeypatch):
    cfg = tmp_path / "llm.yml"
    cfg.write_text("providers: []\n", encoding="utf-8")
    monkeypatch.setenv("RST_LLM_CONFIG", str(cfg))
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "m")
    assert llm_router.load_router().providers == []


# ── alert ingest: cold-start lookback ────────────────────────────────────────

def test_cold_start_lookback_default_and_override(monkeypatch):
    monkeypatch.delenv("RST_ALERT_INGEST_LOOKBACK", raising=False)
    assert ingest._cold_start_gte() == "now-1h"
    monkeypatch.setenv("RST_ALERT_INGEST_LOOKBACK", "7d")
    assert ingest._cold_start_gte() == "now-7d"
    monkeypatch.setenv("RST_ALERT_INGEST_LOOKBACK", "yesterday")
    assert ingest._cold_start_gte() == "now-1h"


# ── baseline: platform from host.os.* ────────────────────────────────────────

def test_platform_of_host_os_fields():
    assert result_reader.platform_of({"host": {"os": {"platform": "ubuntu"}}}) == "linux"
    assert result_reader.platform_of({"host": {"os": {"family": "windows"}}}) == "windows"
    assert result_reader.platform_of({"host": {"os": {"name": "Microsoft Windows Server 2022"}}}) == "windows"
    assert result_reader.platform_of({"host": {"name": "web01"}}) is None


# ── release_store: default HTTP helpers must not need `requests` ─────────────

def test_release_store_default_http_uses_shipped_client(monkeypatch, tmp_path):
    """The shipped image has httpx, not requests. The download helpers used to
    import requests lazily, so /api/admin/release/download 500-ed on every
    delivered bundle with "No module named 'requests'"."""
    import builtins
    from backend import release_store

    real_import = builtins.__import__

    def _no_requests(name, *a, **k):
        if name == "requests":
            raise ImportError("No module named 'requests'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_requests)

    class _Resp:
        text = "manifest-token"
        def raise_for_status(self): pass
        def iter_bytes(self, chunk_size=0): yield b"abc"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: _Resp())
    assert release_store._default_fetch_text("https://x/m") == "manifest-token"
    dest = tmp_path / "blob.part"
    sha = release_store._default_download_to("https://x/b", dest)
    assert dest.read_bytes() == b"abc"
    assert sha == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
