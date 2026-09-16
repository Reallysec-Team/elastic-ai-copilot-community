"""Prompt injection wiring — private mode prepends the asset block into the
investigate user prompt; cloud mode leaves it out."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import investigate  # noqa: E402
from conftest import premium_core  # noqa: E402


@pytest.mark.asyncio
async def test_investigate_prepends_block_in_private(monkeypatch):
    premium_core("alert_investigation")
    async def fake_block(raw, es=None):
        return "涉及资产:财务DB-01（重要度 high;来源 csv,置信 high）"
    monkeypatch.setattr(investigate, "asset_context_block", fake_block)

    captured = {}

    class FakeResp:
        class choices_item:
            class message:
                content = '{"summary":"x"}'
        choices = [choices_item()]

    class FakeRouter:
        async def chat_completion(self, messages=None, **kw):
            captured["messages"] = messages
            return FakeResp(), None

    monkeypatch.setattr(investigate, "get_router", lambda: FakeRouter())
    monkeypatch.setattr(investigate, "augment_prompt_meta",
                        _async_identity)
    monkeypatch.setattr(investigate, "_gather_context", _async_empty)

    await investigate.investigate_alert({"host.name": "win-db01"}, "logs-*")
    user_msg = captured["messages"][1]["content"]
    assert "财务DB-01" in user_msg


@pytest.mark.asyncio
async def test_investigate_no_block_when_none(monkeypatch):
    premium_core("alert_investigation")
    async def fake_block(raw, es=None):
        return None
    monkeypatch.setattr(investigate, "asset_context_block", fake_block)

    captured = {}

    class FakeResp:
        class choices_item:
            class message:
                content = '{"summary":"x"}'
        choices = [choices_item()]

    class FakeRouter:
        async def chat_completion(self, messages=None, **kw):
            captured["messages"] = messages
            return FakeResp(), None

    monkeypatch.setattr(investigate, "get_router", lambda: FakeRouter())
    monkeypatch.setattr(investigate, "augment_prompt_meta", _async_identity)
    monkeypatch.setattr(investigate, "_gather_context", _async_empty)

    await investigate.investigate_alert({"host.name": "win-db01"}, "logs-*")
    assert "资产语境" not in captured["messages"][1]["content"]


async def _async_identity(prompt, top_k=5):
    return prompt, 0


async def _async_empty(*a, **kw):
    return []
