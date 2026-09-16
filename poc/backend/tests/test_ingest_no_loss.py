"""Alert ingest must not lose alerts. Three confirmed loss paths, pinned.

For a SOC product a silently dropped alert is the worst possible failure: the
operator sees it in Kibana, does not see it here, and nothing anywhere says a
thing.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.alerts import ingest  # noqa: E402


class FakeES:
    """Serves hits from a fixture, honouring range/gte + search_after paging."""

    def __init__(self, docs, batch):
        self.docs = docs           # [(ts, id)] already sorted asc
        self.batch = batch
        self.queries = []

    async def search(self, index=None, body=None):
        self.queries.append(body)
        rng = body["query"]["range"]["@timestamp"]
        assert "gte" in rng, "inclusive lower bound is what stops boundary loss"
        lo = rng["gte"]
        after = body.get("search_after")
        rows = [d for d in self.docs if lo == "now-1h" or d[0] >= lo]
        if after:
            ats, aid = after[0], after[1]
            rows = [d for d in rows if (d[0], d[1]) > (ats, aid)]
        rows = rows[: self.batch]
        return _Resp({"hits": {"hits": [
            {"_id": i, "_source": {"kibana.alert.uuid": i, "@timestamp": ts},
             "sort": [ts, i]}
            for ts, i in rows
        ]}})


class _Resp:
    def __init__(self, body):
        self.body = body


@pytest.fixture
def harness(monkeypatch):
    """Wire ingest to a fake ES + in-memory cursor, capture what got handled."""
    state = {"cursor": None, "handled": [], "cursor_error": None}

    async def fake_load():
        if state["cursor_error"]:
            raise ingest.CursorUnavailable(state["cursor_error"])
        return state["cursor"]

    async def fake_save(ts):
        state["cursor"] = ts

    async def fake_handle(alert):
        aid = alert.get("alert_id")
        if not aid or aid in state["handled"]:
            return False
        state["handled"].append(aid)
        return True

    monkeypatch.setattr(ingest, "_load_cursor", fake_load)
    monkeypatch.setattr(ingest, "_save_cursor", fake_save)
    monkeypatch.setattr(ingest, "handle_new_alert", fake_handle)
    monkeypatch.setattr(ingest, "_source_index", lambda: "alerts-idx")

    class AllowAll:
        def is_allowed(self, _i):
            return True

    monkeypatch.setattr(ingest, "get_whitelist", lambda: AllowAll())
    return state


def _install_es(monkeypatch, docs, batch):
    es = FakeES(docs, batch)
    monkeypatch.setattr(ingest, "get_es", lambda: es)
    return es


def test_same_timestamp_group_straddling_the_batch_cap_is_not_lost(monkeypatch, harness):
    """The confirmed bug: one rule execution writes 205 signals whose last 10
    share a millisecond. With `gt` + a single page, 5 were excluded from every
    future query — gone, with no error."""
    monkeypatch.setattr(ingest, "_BATCH", 200)
    docs = [(f"2026-07-21T10:00:{i // 1000:02d}.{i % 1000:03d}Z", f"u{i}") for i in range(195)]
    docs += [("2026-07-21T10:00:59.999Z", f"u{195 + i}") for i in range(10)]  # tie group
    _install_es(monkeypatch, docs, 200)

    asyncio.run(ingest.tick())
    asyncio.run(ingest.tick())  # a second tick must find the remainder

    assert len(harness["handled"]) == 205, (
        f"lost {205 - len(harness['handled'])} alerts: "
        f"{sorted(set(d[1] for d in docs) - set(harness['handled']))}"
    )


def test_more_than_one_page_sharing_a_single_timestamp_still_drains(monkeypatch, harness):
    """`gte` alone would re-read page 1 forever when a tie group exceeds the
    batch; search_after paging is what makes it terminate."""
    monkeypatch.setattr(ingest, "_BATCH", 50)
    docs = [("2026-07-21T10:00:00.000Z", f"t{i:03d}") for i in range(120)]
    _install_es(monkeypatch, docs, 50)

    asyncio.run(ingest.tick())
    assert len(harness["handled"]) == 120


def test_a_tick_does_not_spin_forever_on_a_full_first_page(monkeypatch, harness):
    """Page cap bounds the work; the backlog resumes next tick rather than
    monopolising the loop."""
    monkeypatch.setattr(ingest, "_BATCH", 10)
    monkeypatch.setattr(ingest, "_MAX_PAGES_PER_TICK", 3)
    docs = [(f"2026-07-21T10:00:00.{i:03d}Z", f"p{i:03d}") for i in range(100)]
    es = _install_es(monkeypatch, docs, 10)

    n = asyncio.run(ingest.tick())
    assert n == 30, "3 pages x 10"
    assert len(es.queries) == 3, "must stop at the cap, not drain everything"

    asyncio.run(ingest.tick())
    # 59, not 60, and that is correct: an inclusive lower bound re-reads the
    # boundary document once per tick. It is deduped by op_type=create rather
    # than counted as new, so one page slot per tick is spent on it. That is the
    # price of `gte`, and it is the right trade — the alternative (`gt`) loses
    # every alert tied with the boundary timestamp, permanently.
    assert len(harness["handled"]) == 59, "the next tick resumes from the cursor"
    assert harness["handled"] == sorted(harness["handled"]), "no gaps, in order"


def test_cursor_advances_so_a_quiet_cluster_does_not_re_read(monkeypatch, harness):
    monkeypatch.setattr(ingest, "_BATCH", 200)
    docs = [("2026-07-21T10:00:00.001Z", "a"), ("2026-07-21T10:00:00.002Z", "b")]
    es = _install_es(monkeypatch, docs, 200)

    asyncio.run(ingest.tick())
    assert harness["cursor"] == "2026-07-21T10:00:00.002Z"
    before = len(es.queries)
    assert asyncio.run(ingest.tick()) == 0, "boundary re-read is deduped, not re-counted"
    assert len(es.queries) > before


def test_an_unreadable_cursor_skips_the_tick_instead_of_resetting_to_one_hour(
    monkeypatch, harness
):
    """A 403 on the cursor index is not a cold start. Treating it as one reset
    the tail to now-1h every tick and lost anything older."""
    monkeypatch.setattr(ingest, "_BATCH", 200)
    es = _install_es(monkeypatch, [("2026-07-21T10:00:00.000Z", "x")], 200)
    harness["cursor_error"] = "403 forbidden"

    assert asyncio.run(ingest.tick()) == 0
    assert es.queries == [], "must not query at all with an unknown position"
    assert harness["handled"] == []


# ── webhook (source B) ──────────────────────────────────────────────────────

def test_a_webhook_payload_without_a_kibana_uuid_is_still_ingested(monkeypatch):
    """The confirmed bug: a Kibana webhook body is an operator-authored Mustache
    template. Without kibana.alert.uuid / signal.group.id / event.id the alert
    got alert_id="" and was dropped by store_alert with no log — while the
    endpoint answered 200 {"ingested":0}, which reads as "duplicate"."""
    from fastapi.testclient import TestClient

    from backend import alerts_routes, main

    monkeypatch.setenv("RST_ALERT_WEBHOOK_SECRET", "s3cret")
    seen = []

    async def fake_handle(alert, **kw):
        seen.append(alert)
        return True

    monkeypatch.setattr(alerts_routes.ingest, "handle_new_alert", fake_handle)

    body = {"rule": {"name": "Brute Force"}, "host": {"name": "h1"},
            "@timestamp": "2026-07-21T10:00:00Z"}
    r = TestClient(main.app).post("/api/alerts/ingest", json=body,
                                  headers={"X-RST-Alert-Token": "s3cret"})
    assert r.status_code == 200, r.text
    assert r.json()["ingested"] == 1
    assert seen and seen[0]["alert_id"], "an alert with no id is silently unstorable"


def test_the_webhook_fallback_id_is_stable_so_retries_dedup(monkeypatch):
    """A random id would duplicate the alert on every connector retry."""
    from backend.alerts_routes import _fallback_alert_id

    body = {"rule": {"name": "X"}, "n": 1}
    assert _fallback_alert_id(body) == _fallback_alert_id(dict(reversed(list(body.items()))))
    assert _fallback_alert_id(body) != _fallback_alert_id({"rule": {"name": "Y"}, "n": 1})
