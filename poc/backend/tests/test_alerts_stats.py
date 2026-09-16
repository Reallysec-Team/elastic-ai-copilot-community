"""`/api/alerts/stats` — the overview above the live feed.

Two rules this endpoint exists to keep:

  * it ignores `severity`. The severity mix IS the overview; computing it from
    a severity-filtered set leaves one slice at 100%, so the picture would
    change every time the operator narrowed the list it describes.
  * `/api/alerts/stats` must not be read as `/api/alerts/{alert_id}` with the
    id "stats". FastAPI matches routes in declaration order, so this is a
    property of where the route sits in the file — worth a test, because
    moving it would break it silently (a 404 for an alert named "stats").
"""
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent  # .../poc
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))


import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import license_state, main  # noqa: E402
from backend.alerts import store  # noqa: E402


@pytest.fixture(autouse=True)
def _licensed(monkeypatch):
    monkeypatch.setattr(
        license_state, "get_state",
        lambda: {"status": license_state.STATUS_VALID, "features": ["*"]},
    )


class _Resp:
    def __init__(self, body):
        self.body = body


class _ES:
    def __init__(self, body):
        self._body = body
        self.last_body = None

    async def search(self, index, body):  # noqa: A002 - ES client signature
        self.last_body = body
        return _Resp(self._body)


_BODY = {
    "hits": {"total": {"value": 42}},
    "aggregations": {
        "by_severity": {"buckets": [{"key": "high", "doc_count": 30},
                                    {"key": "low", "doc_count": 12}]},
        "by_rule": {"buckets": [{"key": "Brute force", "doc_count": 30}]},
        "over_time": {"buckets": [
            {"key_as_string": "2026-09-05T08:00:00.000Z", "doc_count": 30},
            {"key_as_string": "2026-09-05T09:00:00.000Z", "doc_count": 12},
        ]},
    },
}


def _client(monkeypatch, es):
    monkeypatch.setattr("backend.es_client.get_es", lambda: es)
    monkeypatch.setattr("backend.alerts.store.get_es", lambda: es)
    return TestClient(main.app)


def test_stats_route_is_not_shadowed_by_the_alert_id_route(monkeypatch):
    es = _ES(_BODY)
    r = _client(monkeypatch, es).get("/api/alerts/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 42
    assert body["by_severity"] == [{"key": "high", "count": 30},
                                   {"key": "low", "count": 12}]
    assert body["by_rule"] == [{"key": "Brute force", "count": 30}]
    assert [p["count"] for p in body["over_time"]] == [30, 12]


def test_severity_is_never_a_filter(monkeypatch):
    """Passing it changes nothing: the mix still describes the whole window."""
    es = _ES(_BODY)
    client = _client(monkeypatch, es)

    client.get("/api/alerts/stats")
    without = es.last_body["query"]

    client.get("/api/alerts/stats?severity=high")
    assert es.last_body["query"] == without


def test_rule_and_range_do_filter(monkeypatch):
    es = _ES(_BODY)
    _client(monkeypatch, es).get(
        "/api/alerts/stats?rule=brute&since=2026-09-05T10:00:00Z&until=2026-09-05T11:00:00Z"
    )
    must = es.last_body["query"]["bool"]["must"]
    assert any("range" in m for m in must)
    assert any("bool" in m for m in must)  # the rule wildcard pair
    # A one-hour window gets minute buckets, not one column.
    assert es.last_body["aggs"]["over_time"]["date_histogram"]["fixed_interval"] == "5m"


def test_no_index_yet_reads_as_an_empty_overview(monkeypatch):
    class _Broken:
        async def search(self, index, body):  # noqa: A002
            raise RuntimeError("index_not_found_exception")

    body = _client(monkeypatch, _Broken()).get("/api/alerts/stats").json()
    assert body == {"total": 0, "by_severity": [], "by_rule": [], "over_time": []}


def test_histogram_interval_helper():
    assert store._histogram_interval(None, None) == "1h"
    assert store._histogram_interval("2026-09-05T10:00:00Z", "2026-09-05T11:00:00Z") == "5m"
    assert store._histogram_interval("2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z") == "1d"
    assert store._histogram_interval("not-a-date", None) == "1h"
