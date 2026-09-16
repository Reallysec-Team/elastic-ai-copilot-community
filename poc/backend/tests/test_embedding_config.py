"""embeddings.py yml 配置层:读 / 写(保留 providers) / configured 判定。"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import embeddings  # noqa: E402


def _cfg(tmp_path, monkeypatch):
    p = tmp_path / "llm.yml"
    monkeypatch.setenv("RST_LLM_CONFIG", str(p))
    return p


def test_load_returns_none_when_file_missing(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    assert embeddings.load_embedding_config() is None


def test_load_returns_none_when_no_embedding_key(tmp_path, monkeypatch):
    p = _cfg(tmp_path, monkeypatch)
    p.write_text("providers:\n  - id: a\n    base_url: http://x\n    api_key: k\n    model: m\n", encoding="utf-8")
    assert embeddings.load_embedding_config() is None


def test_load_returns_none_when_model_empty(tmp_path, monkeypatch):
    p = _cfg(tmp_path, monkeypatch)
    p.write_text("embedding:\n  model: ''\n  dims: 1024\n  enabled: true\n", encoding="utf-8")
    assert embeddings.load_embedding_config() is None


def test_load_reads_full_config(tmp_path, monkeypatch):
    p = _cfg(tmp_path, monkeypatch)
    p.write_text(
        "embedding:\n  model: doubao-embed\n  base_url: https://ark/api/v3\n"
        "  api_key: sk-xyz\n  dims: 2048\n  enabled: true\n",
        encoding="utf-8",
    )
    c = embeddings.load_embedding_config()
    assert c == {
        "model": "doubao-embed",
        "base_url": "https://ark/api/v3",
        "api_key": "sk-xyz",
        "dims": 2048,
        "enabled": True,
    }


def test_save_writes_embedding_and_preserves_providers(tmp_path, monkeypatch):
    p = _cfg(tmp_path, monkeypatch)
    p.write_text(
        "providers:\n  - id: a\n    base_url: http://x\n    api_key: k\n    model: m\n"
        "routing:\n  strategy: failover\n",
        encoding="utf-8",
    )
    embeddings.save_embedding_config({
        "model": "doubao-embed", "base_url": "", "api_key": "sk-1", "dims": 1024, "enabled": True,
    })
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert raw["providers"][0]["id"] == "a"          # providers 未丢
    assert raw["routing"]["strategy"] == "failover"  # routing 未丢
    assert raw["embedding"]["model"] == "doubao-embed"
    assert raw["embedding"]["dims"] == 1024


def test_configured_true_from_yml(tmp_path, monkeypatch):
    p = _cfg(tmp_path, monkeypatch)
    monkeypatch.delenv("RST_EMBED_MODEL", raising=False)
    p.write_text("embedding:\n  model: m\n  dims: 8\n  enabled: true\n", encoding="utf-8")
    assert embeddings.embedding_configured() is True


def test_configured_false_when_disabled_and_no_env(tmp_path, monkeypatch):
    p = _cfg(tmp_path, monkeypatch)
    monkeypatch.delenv("RST_EMBED_MODEL", raising=False)
    p.write_text("embedding:\n  model: m\n  dims: 8\n  enabled: false\n", encoding="utf-8")
    assert embeddings.embedding_configured() is False


def test_configured_true_from_env_fallback(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    monkeypatch.setenv("RST_EMBED_MODEL", "text-embedding-3-small")
    assert embeddings.embedding_configured() is True
