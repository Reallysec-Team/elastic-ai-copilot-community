"""analysis_store.record — assembles AnalysisRecord, best-effort ES index."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import analysis_store  # noqa: E402


class FakeES:
    def __init__(self):
        self.last_index = None
        self.last_id = None
        self.last_doc = None

    async def index(self, index=None, id=None, document=None, refresh=None):
        self.last_index, self.last_id, self.last_doc = index, id, document
        return {"result": "created"}


@pytest.mark.asyncio
async def test_record_assembles_investigation_fields():
    es = FakeES()
    doc = {"alert_type": "SSH 暴力破解", "summary": "多次失败登录", "severity": "high",
           "affected_assets": [{"type": "host", "id": "WIN-DB01"}], "degraded": False}
    rec_id = await analysis_store.record("investigation", doc, owner="alice", es=es)
    assert rec_id and es.last_id == rec_id
    saved = es.last_doc
    assert saved["kind"] == "investigation"
    assert saved["owner"] == "alice"
    assert saved["title"] == "SSH 暴力破解"
    assert saved["summary"] == "多次失败登录"
    assert saved["severity"] == "high"
    assert saved["subject"] == {"type": "host", "value": "WIN-DB01"}
    assert saved["degraded"] is False
    assert saved["payload"] == doc
    assert isinstance(saved["created_at"], float)
    assert "masking_mode" in saved


@pytest.mark.asyncio
async def test_record_derives_triage_from_top_cluster():
    es = FakeES()
    doc = {"total_clusters": 3, "degraded": False, "clusters": [
        {"priority_rank": 1, "severity": "critical", "recommendation": "立即隔离主机"},
        {"priority_rank": 2, "severity": "low", "recommendation": "观察"}]}
    await analysis_store.record("triage", doc, owner=None, es=es)
    saved = es.last_doc
    assert saved["title"] == "3 个 cluster 分诊"
    assert saved["summary"] == "立即隔离主机"
    assert saved["severity"] == "critical"      # max across clusters
    assert saved["subject"] == {"type": "triage", "value": "3 clusters"}


@pytest.mark.asyncio
async def test_record_malformed_payload_uses_safe_defaults():
    es = FakeES()
    await analysis_store.record("investigation", {}, es=es)
    saved = es.last_doc
    assert saved["title"] == "unknown"
    assert saved["summary"] == ""
    assert saved["severity"] == "info"
    assert saved["subject"] == {"type": "unknown", "value": ""}


@pytest.mark.asyncio
async def test_record_es_failure_returns_none():
    class Boom:
        async def index(self, **kw):
            raise RuntimeError("es down")
    assert await analysis_store.record("triage", {"clusters": []}, es=Boom()) is None
