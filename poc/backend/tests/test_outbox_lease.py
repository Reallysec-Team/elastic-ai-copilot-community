"""A delivery must survive the gateway dying mid-send.

`sending` was a terminal state by accident: only _deliver moved a job out of
it, and after a restart _deliver never ran for that job again. asyncio cancels
tasks on shutdown, and CancelledError is a BaseException, so it slipped past
_deliver's `except Exception` too. Net effect for the operator: the critical
alert's Feishu card never arrives, /api/notify/deliveries shows `sending`
forever, and there is no dead-letter to look in.
"""
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.notify import outbox  # noqa: E402


class CapturingES:
    """Records the search body so we can assert on the due-jobs query."""

    def __init__(self):
        self.bodies = []

    async def search(self, index=None, body=None):
        self.bodies.append(body)
        return type("R", (), {"body": {"hits": {"hits": []}}})()


@pytest.mark.asyncio
async def test_due_jobs_reclaims_deliveries_whose_lease_expired(monkeypatch):
    es = CapturingES()
    monkeypatch.setattr(outbox, "get_es", lambda: es)

    await outbox._due_jobs()

    q = es.bodies[0]["query"]["bool"]
    clauses = repr(q["should"])
    assert "sending" in clauses, "expired claims must become due again"
    assert "claimed_at" in clauses, "reclaim has to be time-bounded, not blanket"
    # The original behaviour must survive: queued/failed still become due.
    assert "queued" in clauses and "failed" in clauses


@pytest.mark.asyncio
async def test_the_reclaim_window_is_the_configured_lease(monkeypatch):
    es = CapturingES()
    monkeypatch.setattr(outbox, "get_es", lambda: es)
    fixed = datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(outbox, "_now", lambda: fixed)
    monkeypatch.setattr(outbox, "_CLAIM_LEASE_S", 120.0)

    await outbox._due_jobs()

    stale = re.search(r"'lt': '([^']+)'", repr(es.bodies[0]))
    assert stale, "the sending branch must carry a lower bound"
    assert stale.group(1) == (fixed - timedelta(seconds=120)).isoformat()


@pytest.mark.asyncio
async def test_claim_stamps_the_lease(monkeypatch):
    """Without claimed_at there is nothing for the reclaim query to compare."""
    captured = {}

    class ES:
        async def index(self, index=None, id=None, document=None, **kw):
            captured["doc"] = document
            # 真 ES 的 index() 一定带版本号回来。替身原来返回 None，而 _claim 现在
            # 读不到 _seq_no 就放弃这次 claim（否则终态写入退化成无保护覆盖，正是
            # test_notify_outbox_concurrency 要防的「超时 sender 复活已投递任务」）。
            return {"_seq_no": 1, "_primary_term": 1}

    monkeypatch.setattr(outbox, "get_es", lambda: ES())
    hit = {"_id": "alert:r1:t1", "_seq_no": 1, "_primary_term": 1,
           "_source": {"status": "queued", "attempts": 0}}

    assert await outbox._claim(hit) is True
    assert captured["doc"]["status"] == "sending"
    assert captured["doc"].get("claimed_at"), "no lease stamp = unreclaimable"


@pytest.mark.asyncio
async def test_shutdown_mid_send_releases_the_claim(monkeypatch):
    """Cancellation must not leave the job wedged, and must still propagate."""
    import asyncio

    finished = {}

    async def boom(*a, **kw):
        raise asyncio.CancelledError()

    # **kw absorbs the claim version _deliver now threads through; without it
    # the TypeError is swallowed by the shutdown path's suppress() and this
    # test goes green while asserting nothing.
    async def fake_finish(doc_id, src, *, ok, error="", retryable=False, **kw):
        finished.update(doc_id=doc_id, ok=ok, error=error, retryable=retryable)

    monkeypatch.setattr(outbox.feishu, "send", boom)
    monkeypatch.setattr(outbox, "_finish", fake_finish)
    monkeypatch.setattr(outbox.secret_box, "decrypt", lambda s: "")

    hit = {"_id": "alert:r1:t1",
           "_source": {"webhook_url": "https://open.feishu.cn/x", "body": {}}}

    with pytest.raises(asyncio.CancelledError):
        await outbox._deliver(hit)

    assert finished.get("retryable") is True, "must be retried, not silently dropped"
    assert finished.get("ok") is False
