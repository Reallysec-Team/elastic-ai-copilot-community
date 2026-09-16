"""Feishu docs export — cover the only non-trivial pure logic (markdown→blocks
+ the credential guard). The live Open API calls need real app credentials and
are validated separately against a real Feishu app."""
from __future__ import annotations

import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.notify import feishu_docs as fd  # noqa: E402


def test_blocks_skip_blank_lines_and_shape():
    blocks = fd._markdown_to_blocks("# 标题\n\n正文一\n\n\n正文二\n")
    contents = [b["text"]["elements"][0]["text_run"]["content"] for b in blocks]
    assert contents == ["# 标题", "正文一", "正文二"]
    assert all(b["block_type"] == 2 for b in blocks)


def test_blocks_cap_and_truncation_marker():
    big = "\n".join(f"line {i}" for i in range(fd._MAX_BLOCKS + 50))
    blocks = fd._markdown_to_blocks(big)
    assert len(blocks) == fd._MAX_BLOCKS + 1  # capped + one truncation notice
    assert "截断" in blocks[-1]["text"]["elements"][0]["text_run"]["content"]


def test_credentials_none_without_env(monkeypatch):
    monkeypatch.delenv("RST_FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("RST_FEISHU_APP_SECRET", raising=False)
    assert fd.credentials() is None
    monkeypatch.setenv("RST_FEISHU_APP_ID", "a")
    monkeypatch.setenv("RST_FEISHU_APP_SECRET", "b")
    assert fd.credentials() == ("a", "b")


if __name__ == "__main__":  # pragma: no cover
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
