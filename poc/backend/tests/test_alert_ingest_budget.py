"""webhook 批量接入的并发上限与摘要时间预算。

一次推送最多带 200 条告警，每条要过一次 LLM 摘要。串行跑下来能到几分钟，而
Kibana 的 connector 到点就重发同一批 —— 整批再走一遍，LLM 再花一遍。所以：
并发有上限（不是无限并发去打 LLM），摘要有时间预算（超了就不摘要，但照旧入库）。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from fastapi.testclient import TestClient  # noqa: E402

from backend import license_state, main as m  # noqa: E402
from backend.alerts import ingest  # noqa: E402

_ALERT = {"kibana.alert.rule.name": "r", "@timestamp": "2026-09-10T00:00:00Z"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        license_state, "get_state",
        lambda: {"status": license_state.STATUS_VALID, "features": ["*"]},
    )
    monkeypatch.setenv("RST_ALERT_WEBHOOK_SECRET", "s3cret")
    return TestClient(m.app)


def _post(client, n: int):
    return client.post(
        "/api/alerts/ingest",
        json={"alerts": [dict(_ALERT, **{"kibana.alert.uuid": f"u-{i}"}) for i in range(n)]},
        headers={"X-RST-Alert-Token": "s3cret"},
    )


@pytest.fixture
def isolated_ingest(monkeypatch):
    """跑真的 handle_new_alert 时，把派发和 ES 单例隔开。

    `asyncio.run(...)` 每次起一个新的事件循环，而 `get_es()` 的客户端是模块级单例：
    在这个循环里建出来，下一个用 TestClient 的用例再拿到它就是「Event loop is closed」。
    这些用例要证的是摘要标记，不是投递，所以把 dispatch 桩掉，跑完复位单例。
    """
    from backend import es_client
    from backend.notify import outbox

    async def no_dispatch(alert, ref):
        return 0

    monkeypatch.setattr(outbox, "dispatch_alert", no_dispatch)
    ingest._summary_skipped.clear()
    yield
    ingest._summary_skipped.clear()
    es_client._es = None


def _record_flags(monkeypatch) -> list[bool]:
    flags: list[bool] = []

    async def fake_handle(alert, *, summarize=True):
        flags.append(summarize)
        return True

    monkeypatch.setattr(ingest, "handle_new_alert", fake_handle)
    return flags


def test_within_budget_everything_gets_a_summary(client, monkeypatch):
    flags = _record_flags(monkeypatch)
    r = _post(client, 5)
    assert r.status_code == 200, r.text
    assert r.json()["ingested"] == 5
    assert r.json()["without_summary"] == 0
    assert flags == [True] * 5


def test_past_the_budget_alerts_still_land_without_a_summary(client, monkeypatch):
    """预算用完不是丢告警，是不再花 LLM —— 丢摘要好过丢告警。"""
    monkeypatch.setenv("RST_ALERT_INGEST_BUDGET_S", "0.001")
    # 串行 + 每条 20ms，好让预算在第一条之后确实用完（Windows 上 monotonic 的
    # 分辨率有十几毫秒，靠「预算小」本身是撞不出来的）。
    monkeypatch.setenv("RST_ALERT_INGEST_CONCURRENCY", "1")
    flags: list[bool] = []

    async def slow(alert, *, summarize=True):
        flags.append(summarize)
        await asyncio.sleep(0.02)
        return True

    monkeypatch.setattr(ingest, "handle_new_alert", slow)
    r = _post(client, 4)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ingested"] == 4                # 一条都没丢
    assert body["without_summary"] >= 3         # 预算之后的都不再花 LLM
    assert flags[-1] is False


def test_items_are_processed_concurrently_but_bounded(client, monkeypatch):
    monkeypatch.setenv("RST_ALERT_INGEST_CONCURRENCY", "3")
    inflight = 0
    peak = 0

    async def slow_handle(alert, *, summarize=True):
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        await asyncio.sleep(0.02)
        inflight -= 1
        return True

    monkeypatch.setattr(ingest, "handle_new_alert", slow_handle)
    r = _post(client, 9)
    assert r.status_code == 200, r.text
    assert r.json()["ingested"] == 9
    assert peak > 1, "还是串行的"
    assert peak <= 3, f"并发没有被上限挡住：峰值 {peak}"


def test_one_bad_item_does_not_sink_the_batch(client, monkeypatch):
    async def flaky(alert, *, summarize=True):
        if alert.get("alert_id", "").endswith("u-2"):
            raise RuntimeError("ES write blew up")
        return True

    monkeypatch.setattr(ingest, "handle_new_alert", flaky)
    r = _post(client, 4)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ingested"] == 3
    assert body["failed"] == 1


def test_a_skipped_summary_is_marked_on_the_alert_and_counted(monkeypatch, isolated_ingest):
    """跳过摘要要留痕：文档上一个标记，接入状态里一个计数。

    没有这两样的话，运维看到一批告警突然没摘要，无从判断是关掉了、失败了、还是
    撞上了预算 —— 三种情况在界面上长得一模一样。
    """
    from backend.alerts import store

    stored: list[dict] = []

    async def fake_exists(alert_id):
        return False

    async def fake_store(alert):
        stored.append(alert)
        return True

    async def never_summarize(alert):
        raise AssertionError("跳过时不该再花 LLM")

    monkeypatch.setattr(store, "exists", fake_exists)
    monkeypatch.setattr(store, "store_alert", fake_store)
    monkeypatch.setattr(ingest, "summarize_alert", never_summarize)
    ingest._summary_skipped.clear()

    alert = {"alert_id": "u-9", "rule_name": "r", "severity": "high"}
    assert asyncio.run(ingest.handle_new_alert(alert, summarize=False)) is True

    assert stored and stored[0]["summary_skipped"] is True
    assert ingest.summary_skipped_recent() == 1
    ingest._summary_skipped.clear()


def test_a_generated_summary_leaves_no_skip_mark(monkeypatch, isolated_ingest):
    from backend.alerts import store

    stored: list[dict] = []

    async def fake_exists(alert_id):
        return False

    async def fake_store(alert):
        stored.append(alert)
        return True

    async def fake_summarize(alert):
        return "一句话"

    monkeypatch.setattr(store, "exists", fake_exists)
    monkeypatch.setattr(store, "store_alert", fake_store)
    monkeypatch.setattr(ingest, "summarize_alert", fake_summarize)
    ingest._summary_skipped.clear()

    assert asyncio.run(ingest.handle_new_alert({"alert_id": "u-10"}, summarize=True)) is True
    assert stored[0]["summary"] == "一句话"
    assert "summary_skipped" not in stored[0]
    assert ingest.summary_skipped_recent() == 0


def test_the_ingest_status_reports_the_skip_count_and_the_knobs(client, monkeypatch):
    monkeypatch.setenv("RST_ALERT_INGEST_BUDGET_S", "7")
    monkeypatch.setenv("RST_ALERT_INGEST_CONCURRENCY", "3")
    ingest._summary_skipped.clear()
    ingest._note_summary_skipped()
    ingest._note_summary_skipped()

    r = client.get("/api/alerts/ingest/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary_skipped_recent"] == 2
    assert body["summary_budget_s"] == 7
    assert body["summary_concurrency"] == 3
    ingest._summary_skipped.clear()
