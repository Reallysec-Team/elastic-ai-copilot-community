import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import report_agg  # noqa: E402


class FakeES:
    def __init__(self, resp=None, boom=False):
        self._resp, self._boom = resp, boom
        self.last_body = None

    async def search(self, index=None, body=None):
        if self._boom:
            raise RuntimeError("no such index")
        self.last_body = body
        return type("R", (), {"body": self._resp})()


@pytest.mark.asyncio
async def test_analysis_activity_maps_kind_and_high_ratio():
    resp = {
        "hits": {"total": {"value": 10}},
        "aggregations": {
            "by_kind": {"buckets": [{"key": "triage", "doc_count": 6},
                                    {"key": "investigation", "doc_count": 4}]},
            "by_sev": {"buckets": [{"key": "high", "doc_count": 3},
                                   {"key": "critical", "doc_count": 2},
                                   {"key": "low", "doc_count": 5}]},
            "top_topics": {"buckets": [{"key": "SSH 暴力破解", "doc_count": 4},
                                       {"key": "端口扫描", "doc_count": 3}]},
        },
    }
    es = FakeES(resp)
    out = await report_agg.analysis_activity(es, 1000.0, 2000.0)
    assert out["total"] == 10
    assert out["by_kind"] == {"triage": 6, "investigation": 4}
    assert out["high_ratio"] == 0.5  # (3+2)/10
    assert out["top_topics"] == ["SSH 暴力破解", "端口扫描"]
    # window applied on created_at
    rng = es.last_body["query"]["bool"]["filter"][0]["range"]["created_at"]
    assert rng["gte"] == 1000.0 and rng["lte"] == 2000.0


@pytest.mark.asyncio
async def test_analysis_activity_degrades_on_error():
    out = await report_agg.analysis_activity(FakeES(boom=True), 0.0, 1.0)
    assert out == {"total": 0, "by_kind": {"triage": 0, "investigation": 0},
                   "high_ratio": 0.0, "top_topics": [],
                   # zeros the report must NOT present as "no activity"
                   "degraded": "no such index"}
