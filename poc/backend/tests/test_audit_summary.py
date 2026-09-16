"""`/api/audit/events` now returns a `summary` beside the page of events.

The page draws call volume, outcome mix and latency from it. Two things have
to hold, and both are easy to get wrong when flattening ES aggregations:

  * the summary describes the WHOLE filtered window, not the 50 rows on
    screen — otherwise the chart labels "the last page" as "today";
  * a percentile with no timings behind it stays null. ES returns null there,
    and defaulting it to 0 would draw "nothing was recorded" as "took 0 ms".
"""
import os
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent  # .../poc
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

os.environ.pop("RST_GATEWAY_SHARED_SECRET", None)
os.environ.pop("RST_ADMIN_TOKEN", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import license_state, main  # noqa: E402


@pytest.fixture(autouse=True)
def _licensed(monkeypatch):
    monkeypatch.setattr(
        license_state, "get_state",
        lambda: {"status": license_state.STATUS_VALID, "features": ["*"]},
    )


class _Resp:
    def __init__(self, body):
        self.body = body


def _es_returning(body):
    class _ES:
        def __init__(self):
            self.last_body = None

        async def search(self, index, body):  # noqa: A002 - ES client signature
            self.last_body = body
            return _Resp(body_)

    body_ = body
    return _ES()


def _client(monkeypatch, es):
    monkeypatch.setattr("backend.es_client.get_es", lambda: es)
    monkeypatch.setattr(main, "require_admin", lambda request: None)
    return TestClient(main.app)


_AGGS = {
    "over_time": {
        "buckets": [
            {"key_as_string": "2026-09-05T08:00:00.000Z", "key": 1, "doc_count": 12,
             "failed": {"doc_count": 2}},
            {"key_as_string": "2026-09-05T09:00:00.000Z", "key": 2, "doc_count": 0,
             "failed": {"doc_count": 0}},
        ]
    },
    "by_action": {"buckets": [{"key": "generate", "doc_count": 9},
                              {"key": "execute", "doc_count": 3}]},
    "by_outcome": {"buckets": [{"key": "ok", "doc_count": 10},
                               {"key": "error", "doc_count": 2}]},
    "by_user": {"buckets": [{"key": "admin", "doc_count": 12}]},
    "duration": {"values": {"50.0": 240.0, "95.0": 1800.0}},
}


def test_summary_covers_the_window_not_the_page(monkeypatch):
    """total is 12 while the page holds 1 row: the summary follows total."""
    es = _es_returning({
        "hits": {"total": {"value": 12}, "hits": [{"_source": {"action": "generate"}}]},
        "aggregations": _AGGS,
    })
    r = _client(monkeypatch, es).get("/api/audit/events?size=1")
    assert r.status_code == 200
    body = r.json()

    assert body["total"] == 12
    assert len(body["events"]) == 1

    s = body["summary"]
    assert sum(p["count"] for p in s["over_time"]) == 12
    assert s["over_time"][0]["failed"] == 2
    # Empty buckets survive: a quiet hour is a gap in the line, not a missing point.
    assert s["over_time"][1]["count"] == 0
    assert s["by_action"] == [{"key": "generate", "count": 9},
                              {"key": "execute", "count": 3}]
    assert s["by_outcome"] == [{"key": "ok", "count": 10},
                               {"key": "error", "count": 2}]
    assert s["by_user"] == [{"key": "admin", "count": 12}]
    assert s["duration_p50_ms"] == 240.0
    assert s["duration_p95_ms"] == 1800.0

    # The aggregations ride the same filtered query as the page.
    assert "aggs" in es.last_body
    assert es.last_body["query"]["bool"]["filter"]


def test_percentiles_stay_null_when_nothing_was_timed(monkeypatch):
    aggs = dict(_AGGS, duration={"values": {"50.0": None, "95.0": None}})
    es = _es_returning({"hits": {"total": {"value": 2}, "hits": []},
                        "aggregations": aggs})
    s = _client(monkeypatch, es).get("/api/audit/events").json()["summary"]
    assert s["duration_p50_ms"] is None
    assert s["duration_p95_ms"] is None


def test_missing_index_still_answers_with_an_empty_summary(monkeypatch):
    class _ES:
        async def search(self, index, body):  # noqa: A002
            raise RuntimeError("index_not_found_exception")

    body = _client(monkeypatch, _ES()).get("/api/audit/events").json()
    assert body["total"] == 0
    assert body["summary"]["over_time"] == []
    assert body["summary"]["duration_p95_ms"] is None


def test_bucket_width_follows_the_window(monkeypatch):
    """A 1h window gets 5m buckets, a week gets days — one width cannot do both."""
    es = _es_returning({"hits": {"total": {"value": 0}, "hits": []}, "aggregations": _AGGS})
    client = _client(monkeypatch, es)

    client.get("/api/audit/events?from_ts=2026-09-05T10:00:00Z&to_ts=2026-09-05T11:00:00Z")
    assert es.last_body["aggs"]["over_time"]["date_histogram"]["fixed_interval"] == "5m"

    client.get("/api/audit/events?from_ts=2026-09-05T00:00:00Z&to_ts=2026-09-06T00:00:00Z")
    assert es.last_body["aggs"]["over_time"]["date_histogram"]["fixed_interval"] == "1h"

    client.get("/api/audit/events?from_ts=2026-08-30T00:00:00Z&to_ts=2026-09-06T00:00:00Z")
    assert es.last_body["aggs"]["over_time"]["date_histogram"]["fixed_interval"] == "1d"

    # Unparseable / absent bounds fall back to the default window's width.
    client.get("/api/audit/events?from_ts=not-a-date")
    assert es.last_body["aggs"]["over_time"]["date_histogram"]["fixed_interval"] == "1h"


def test_histogram_spans_the_window_not_just_the_hits(monkeypatch):
    """Without extended_bounds one busy minute draws a lone dot, not a line."""
    es = _es_returning({"hits": {"total": {"value": 0}, "hits": []}, "aggregations": _AGGS})
    _client(monkeypatch, es).get("/api/audit/events?from_ts=2026-09-05T10:00:00Z")
    bounds = es.last_body["aggs"]["over_time"]["date_histogram"]["extended_bounds"]
    assert bounds == {"min": "2026-09-05T10:00:00Z", "max": "now"}
