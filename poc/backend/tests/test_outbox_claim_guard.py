"""Outbox 的三处兜底：claim 没版本号就别发、老 sending 文档也要能被接管、退避抖动真随机。

覆盖的都是「表面上有保护、实际上没有」的那类 bug —— 空的 CAS、匹配不到任何文档的
range、同一毫秒恒等的抖动。
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.notify import outbox  # noqa: E402


def test_claim_without_a_version_is_refused(monkeypatch):
    """读不到 _seq_no = _finish 的 CAS 会退化成无保护覆盖，宁可不发。"""
    class ES:
        async def index(self, **kw):
            return {"result": "updated"}   # 没有 _seq_no / _primary_term

    monkeypatch.setattr(outbox, "get_es", lambda: ES())
    hit = {"_id": "d1", "_seq_no": 1, "_primary_term": 1,
           "_source": {"status": "queued", "attempts": 0}}

    assert asyncio.run(outbox._claim(hit)) is False


def test_due_jobs_reclaims_sending_docs_without_a_lease_stamp(monkeypatch):
    """租约上线前写进去的 sending 文档没有 claimed_at，range 匹配不到它们。"""
    captured = {}

    class ES:
        async def search(self, index=None, body=None):
            captured["body"] = body
            return type("R", (), {"body": {"hits": {"hits": []}}})()

    monkeypatch.setattr(outbox, "get_es", lambda: ES())
    asyncio.run(outbox._due_jobs())

    should = captured["body"]["query"]["bool"]["should"]
    missing_stamp = [
        b for b in should
        if {"exists": {"field": "claimed_at"}} in (b.get("bool") or {}).get("must_not", [])
    ]
    assert missing_stamp, "缺 claimed_at 的老 sending 文档会永远卡住"
    assert {"term": {"status": "sending"}} in missing_stamp[0]["bool"]["must"]


def test_claimed_at_is_in_the_mapping():
    assert "claimed_at" in _mapping(outbox)["mappings"]["properties"]


def _mapping(mod):
    """_ensure_index 里的 mapping 是内联的，跑一遍拿到它。"""
    captured = {}

    class Indices:
        async def exists(self, index=None):
            return False

        async def create(self, index=None, body=None):
            captured["body"] = body

    class ES:
        indices = Indices()

    mod._index_ready = False
    orig = mod.get_es
    mod.get_es = lambda: ES()
    try:
        asyncio.run(mod._ensure_index())
    finally:
        mod.get_es = orig
        mod._index_ready = False
    return captured["body"]


def test_backoff_jitter_differs_between_calls():
    """同一毫秒里算出的抖动必须不同 —— 批量失败正是它要拆开的场景。"""
    vals = {outbox._backoff_seconds(3) for _ in range(20)}
    assert len(vals) > 1
    assert all(0.85 * 120 <= v <= 1.15 * 120 for v in vals)
