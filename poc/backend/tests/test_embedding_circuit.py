"""embedding 熔断：端点失败一次后冷却期内直接抛，不再每次等 SDK 重试完。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import embeddings  # noqa: E402


class _Boom:
    calls = 0

    class embeddings:  # noqa: N801 — mimics client.embeddings.create
        @staticmethod
        async def create(**_kw):
            _Boom.calls += 1
            raise ConnectionError("Connection error.")


def test_circuit_opens_after_failure_and_recovers(monkeypatch):
    monkeypatch.setenv("RST_EMBED_COOLDOWN_S", "0.2")
    c = embeddings.EmbeddingClient()
    c._client = _Boom()  # type: ignore[assignment]
    _Boom.calls = 0

    with pytest.raises(ConnectionError):
        asyncio.run(c.embed_texts(["q"]))
    assert _Boom.calls == 1
    # 冷却期内：不碰端点，直接 EmbeddingUnavailable。
    with pytest.raises(embeddings.EmbeddingUnavailable):
        asyncio.run(c.embed_texts(["q"]))
    assert _Boom.calls == 1
    # 冷却到期：再试一次（端点还坏 → 又熔断）。
    asyncio.run(asyncio.sleep(0.25))
    with pytest.raises(ConnectionError):
        asyncio.run(c.embed_texts(["q"]))
    assert _Boom.calls == 2
