"""A duplicate alert must not reach the LLM.

`handle_new_alert` has to summarize before `store_alert` (the summary rides the
single create write, plus the SSE/Feishu payloads), and `store_alert` is also the
dedup — so the pre-check is the only thing standing between a re-read and a paid
summary that gets thrown away. Ingest re-reads the cursor boundary once per tick
by design, and Kibana webhook connectors retry, so this is the steady state, not
an edge case.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.alerts import ingest  # noqa: E402


def _wire(monkeypatch, stored):
    """Fake store keyed on alert_id; count summarize calls."""
    calls = {"summarize": 0}

    async def fake_exists(aid):
        return aid in stored

    async def fake_store(alert):
        aid = alert.get("alert_id") or ""
        if not aid or aid in stored:
            return False
        stored[aid] = alert
        return True

    async def fake_summarize(alert):
        calls["summarize"] += 1
        return "摘要"

    monkeypatch.setattr(ingest.store, "exists", fake_exists)
    monkeypatch.setattr(ingest.store, "store_alert", fake_store)
    # 模块里那个名字现在是 `summarize_alert`：`handle_new_alert` 的开关叫
    # `summarize`，同名会把函数遮住。
    monkeypatch.setattr(ingest, "summarize_alert", fake_summarize)
    monkeypatch.setattr(ingest.broker, "publish", lambda a: None)
    return calls


def test_a_duplicate_does_not_pay_for_a_summary(monkeypatch):
    stored: dict = {}
    calls = _wire(monkeypatch, stored)

    assert asyncio.run(ingest.handle_new_alert({"alert_id": "a1"})) is True
    assert calls["summarize"] == 1
    assert stored["a1"]["summary"] == "摘要", "summary must persist in the create write"

    assert asyncio.run(ingest.handle_new_alert({"alert_id": "a1"})) is False
    assert calls["summarize"] == 1, "the re-read must not reach the LLM again"


def test_a_new_alert_still_gets_summarized(monkeypatch):
    stored: dict = {}
    calls = _wire(monkeypatch, stored)

    asyncio.run(ingest.handle_new_alert({"alert_id": "a1"}))
    asyncio.run(ingest.handle_new_alert({"alert_id": "a2"}))
    assert calls["summarize"] == 2
