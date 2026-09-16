"""save_providers 必须保留已存在的 embedding: 段(反向保留由 test_embedding_config 覆盖)。"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import llm_router  # noqa: E402


def test_save_providers_preserves_embedding(tmp_path, monkeypatch):
    cfg = tmp_path / "llm.yml"
    monkeypatch.setenv("RST_LLM_CONFIG", str(cfg))
    cfg.write_text(
        "embedding:\n  model: doubao-embed\n  dims: 2048\n  enabled: true\n",
        encoding="utf-8",
    )
    llm_router.reset()
    llm_router.save_providers([{
        "id": "a", "base_url": "http://x", "api_key": "k", "model": "m",
    }])
    raw = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert raw["providers"][0]["id"] == "a"          # providers 写入
    assert raw["embedding"]["model"] == "doubao-embed"  # embedding 未被覆盖
    assert raw["embedding"]["dims"] == 2048
