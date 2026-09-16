"""embedding config/test/save 端点。直接调 route handler + monkeypatch seam,无 ASGI。

维度守卫 5 步逐条:model 空→400、探针失败→400、dims 自纠、KB 索引冲突→409、成功→写盘+重置。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import main  # noqa: E402
from backend.schemas import EmbeddingSaveRequest, EmbeddingTestRequest  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class _Req:
    """Minimal stand-in for starlette Request (require_admin is monkeypatched off)."""
    client = type("C", (), {"host": "127.0.0.1"})()
    headers: dict = {}


@pytest.fixture(autouse=True)
def _no_admin(monkeypatch):
    monkeypatch.setattr(main, "require_admin", lambda r: None)
    yield


# ── GET config ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_config_disabled_when_unconfigured(monkeypatch):
    monkeypatch.setattr(main.embeddings, "load_embedding_config", lambda: None)
    monkeypatch.setattr(main.embeddings, "embedding_configured", lambda: False)

    async def _dims(): return None
    monkeypatch.setattr(main.rag.get_kb(), "index_dims", _dims)
    out = await main.embedding_config()
    assert out["status"] == "disabled"
    assert out["kb_index_dims"] is None
    assert out["api_key_set"] is False


@pytest.mark.asyncio
async def test_config_masks_key_and_reports_enabled(monkeypatch):
    monkeypatch.setattr(main.embeddings, "load_embedding_config",
                        lambda: {"model": "m", "base_url": "http://e", "api_key": "sk-abcd1234",
                                 "dims": 2048, "enabled": True})
    monkeypatch.setattr(main.embeddings, "embedding_configured", lambda: True)

    async def _dims(): return 2048
    monkeypatch.setattr(main.rag.get_kb(), "index_dims", _dims)
    out = await main.embedding_config()
    assert out["status"] == "enabled"
    assert out["model"] == "m" and out["dims"] == 2048
    assert out["api_key_set"] is True
    assert out["api_key_last4"] == "1234"
    assert "sk-abcd1234" not in str(out)   # 明文永不出网关
    assert out["kb_index_dims"] == 2048


# ── POST test ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_test_endpoint_ok(monkeypatch):
    async def _probe(model, base_url, api_key): return 1024
    monkeypatch.setattr(main.embeddings, "probe_embedding", _probe)
    out = await main.embedding_test(EmbeddingTestRequest(model="m", base_url="http://e", api_key="k"), _Req())
    assert out == {"ok": True, "dims": 1024}


@pytest.mark.asyncio
async def test_test_endpoint_error(monkeypatch):
    async def _probe(model, base_url, api_key): raise RuntimeError("401 unauthorized")
    monkeypatch.setattr(main.embeddings, "probe_embedding", _probe)
    out = await main.embedding_test(EmbeddingTestRequest(model="m", base_url="http://e", api_key="bad"), _Req())
    assert out["ok"] is False and "401" in out["error"]


# ── POST save (5-step guard) ─────────────────────────────────────────────────

async def _idx_none(): return None


@pytest.mark.asyncio
async def test_save_model_empty_400(monkeypatch):
    with pytest.raises(HTTPException) as e:
        await main.embedding_save(EmbeddingSaveRequest(model="  "), _Req())
    assert e.value.status_code == 400


@pytest.mark.asyncio
async def test_save_probe_fail_400_no_write(monkeypatch):
    async def _probe(model, base_url, api_key): raise RuntimeError("connect refused")
    monkeypatch.setattr(main.embeddings, "probe_embedding", _probe)
    saved = {"called": False}
    monkeypatch.setattr(main.embeddings, "save_embedding_config", lambda c: saved.update(called=True))
    monkeypatch.setattr(main.embeddings, "load_embedding_config", lambda: None)
    with pytest.raises(HTTPException) as e:
        await main.embedding_save(EmbeddingSaveRequest(model="m", base_url="http://e", api_key="k"), _Req())
    assert e.value.status_code == 400
    assert saved["called"] is False   # 探针失败绝不写盘


@pytest.mark.asyncio
async def test_save_autocorrects_dims_and_writes(monkeypatch):
    async def _probe(model, base_url, api_key): return 2048
    monkeypatch.setattr(main.embeddings, "probe_embedding", _probe)
    monkeypatch.setattr(main.embeddings, "load_embedding_config", lambda: None)
    monkeypatch.setattr(main.rag.get_kb(), "index_dims", _idx_none)
    written = {}
    monkeypatch.setattr(main.embeddings, "save_embedding_config", lambda c: written.update(c))
    reset = {"n": 0}
    monkeypatch.setattr(main.embeddings, "reset", lambda: reset.update(n=reset["n"] + 1))
    # body.dims=999 wrong → overwritten with real 2048
    out = await main.embedding_save(
        EmbeddingSaveRequest(model="m", base_url="http://e", api_key="k", dims=999, enabled=True), _Req())
    assert out == {"ok": True, "dims": 2048, "status": "enabled"}
    assert written["dims"] == 2048
    assert reset["n"] == 1   # 单例重置


@pytest.mark.asyncio
async def test_save_index_dim_conflict_409_no_write(monkeypatch):
    async def _probe(model, base_url, api_key): return 2048   # 真实模型 2048 维
    async def _idx_768(): return 768                          # 但既有索引 768 维 → 冲突
    monkeypatch.setattr(main.embeddings, "probe_embedding", _probe)
    monkeypatch.setattr(main.embeddings, "load_embedding_config", lambda: None)
    monkeypatch.setattr(main.rag.get_kb(), "index_dims", _idx_768)
    saved = {"called": False}
    monkeypatch.setattr(main.embeddings, "save_embedding_config", lambda c: saved.update(called=True))
    with pytest.raises(HTTPException) as e:
        await main.embedding_save(EmbeddingSaveRequest(model="m", base_url="http://e", api_key="k"), _Req())
    assert e.value.status_code == 409
    assert "768" in e.value.detail and "2048" in e.value.detail
    assert saved["called"] is False   # 维度冲突绝不写盘


@pytest.mark.asyncio
async def test_save_inherits_stored_key_when_blank(monkeypatch):
    captured = {}
    async def _probe(model, base_url, api_key):
        captured["key"] = api_key
        return 2048
    monkeypatch.setattr(main.embeddings, "probe_embedding", _probe)
    monkeypatch.setattr(main.embeddings, "load_embedding_config",
                        lambda: {"model": "m", "base_url": "http://e", "api_key": "stored-key",
                                 "dims": 2048, "enabled": True})
    monkeypatch.setattr(main.rag.get_kb(), "index_dims", _idx_none)
    monkeypatch.setattr(main.embeddings, "save_embedding_config", lambda c: None)
    monkeypatch.setattr(main.embeddings, "reset", lambda: None)
    await main.embedding_save(EmbeddingSaveRequest(model="m", base_url="http://e", api_key=""), _Req())
    assert captured["key"] == "stored-key"   # 空 key → 继承已存
