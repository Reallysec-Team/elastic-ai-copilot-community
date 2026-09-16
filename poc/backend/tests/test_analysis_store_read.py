"""analysis_store list/get — owner isolation, kind/q filters, before/since, TTL."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import analysis_store  # noqa: E402


class FakeSearchES:
    """Serves docs from an in-memory list, applying the bool filter + sort + size."""
    def __init__(self, docs):
        self._docs = docs  # list of _source dicts
        self.last_body = None

    async def search(self, index=None, body=None):
        self.last_body = body
        filters = body["query"]["bool"]["filter"]
        hits = list(self._docs)
        for f in filters:
            # owner 在映射里就是 keyword 本体，没有 .keyword 子字段。
            if "term" in f and "owner" in f["term"]:
                owner = f["term"]["owner"]
                hits = [h for h in hits if h.get("owner") == owner]
            if "range" in f and "created_at" in f["range"]:
                r = f["range"]["created_at"]
                if "gte" in r:
                    hits = [h for h in hits if h["created_at"] >= r["gte"]]
                if "lt" in r:
                    hits = [h for h in hits if h["created_at"] < r["lt"]]
            if "term" in f and "kind" in f.get("term", {}):
                hits = [h for h in hits if h.get("kind") == f["term"]["kind"]]
            if "simple_query_string" in f:
                sqs = f["simple_query_string"]
                # 够用的替身：按词 AND，在 fields 指定的那几个字段里找子串。
                terms = sqs["query"].split()
                hits = [
                    h for h in hits
                    if all(
                        any(t.lower() in str(h.get(fld, "")).lower() for fld in sqs["fields"])
                        for t in terms
                    )
                ]
        hits.sort(key=lambda h: h["created_at"], reverse=True)
        sized = hits[: body["size"]]
        return {"hits": {"total": {"value": len(hits)},
                         "hits": [{"_source": h} for h in sized]}}


def _doc(rec_id, owner, kind="investigation", created_at=None, sev="high"):
    return {"id": rec_id, "kind": kind, "owner": owner,
            "created_at": created_at if created_at is not None else time.time(),
            "title": "t", "summary": "s", "severity": sev,
            "subject": {"type": "host", "value": rec_id}, "payload": {"x": 1}}


@pytest.mark.asyncio
async def test_list_owner_isolation_and_summary_shape():
    es = FakeSearchES([_doc("a", "alice"), _doc("b", "bob")])
    r = await analysis_store.list_records(None, 50, None, "alice", es=es)
    assert r["total"] == 1
    assert [x["id"] for x in r["records"]] == ["a"]
    assert "payload" not in r["records"][0]           # summary is light
    assert r["records"][0]["subject"] == {"type": "host", "value": "a"}


@pytest.mark.asyncio
async def test_list_kind_filter():
    es = FakeSearchES([_doc("a", None, kind="investigation"), _doc("b", None, kind="triage")])
    r = await analysis_store.list_records("triage", 50, None, None, es=es)
    assert [x["id"] for x in r["records"]] == ["b"]


@pytest.mark.asyncio
async def test_list_before_cursor_excludes_newer():
    now = time.time()
    es = FakeSearchES([_doc("old", None, created_at=now - 100),
                       _doc("new", None, created_at=now)])
    r = await analysis_store.list_records(None, 50, now - 50, None, es=es)
    assert [x["id"] for x in r["records"]] == ["old"]


@pytest.mark.asyncio
async def test_list_ttl_filters_expired():
    old = time.time() - analysis_store._ttl_seconds() - 10
    es = FakeSearchES([_doc("stale", None, created_at=old)])
    r = await analysis_store.list_records(None, 50, None, None, es=es)
    assert r["records"] == []


@pytest.mark.asyncio
async def test_list_es_failure_returns_empty():
    class Boom:
        async def search(self, **kw):
            raise RuntimeError("down")
    r = await analysis_store.list_records(None, 50, None, None, es=Boom())
    assert r == {"total": 0, "records": []}


@pytest.mark.asyncio
async def test_get_owner_mismatch_returns_none():
    class GetES:
        async def get(self, index=None, id=None):
            return {"found": True, "_source": _doc("a", "alice")}
    assert await analysis_store.get_record("a", owner="bob", es=GetES()) is None


@pytest.mark.asyncio
async def test_get_returns_full_payload():
    class GetES:
        async def get(self, index=None, id=None):
            return {"found": True, "_source": _doc("a", "alice")}
    got = await analysis_store.get_record("a", owner="alice", es=GetES())
    assert got["payload"] == {"x": 1}


@pytest.mark.asyncio
async def test_get_ttl_expired_returns_none():
    old = time.time() - analysis_store._ttl_seconds() - 10

    class GetES:
        async def get(self, index=None, id=None):
            return {"found": True, "_source": _doc("a", None, created_at=old)}
    assert await analysis_store.get_record("a", owner=None, es=GetES()) is None


def _doc_text(rec_id, title, summary, created_at=None):
    return {"id": rec_id, "kind": "investigation", "owner": None,
            "created_at": created_at if created_at is not None else time.time(),
            "title": title, "summary": summary, "severity": "high",
            "subject": {"type": "host", "value": rec_id}, "payload": {}}


@pytest.mark.asyncio
async def test_list_q_matches_title_and_summary():
    es = FakeSearchES([
        _doc_text("a", "SSH 暴力破解", "web-prod-03 被撞开"),
        _doc_text("b", "端口扫描", "sqlmap 扫 web-prod-01"),
    ])
    r = await analysis_store.list_records(None, 50, None, None, es=es, q="暴力破解")
    assert [x["id"] for x in r["records"]] == ["a"]

    # summary 也在检索范围里
    r = await analysis_store.list_records(None, 50, None, None, es=es, q="sqlmap")
    assert [x["id"] for x in r["records"]] == ["b"]

    # 多个词是 AND：两个词分别命中不同记录时，谁都不该回
    r = await analysis_store.list_records(None, 50, None, None, es=es, q="暴力破解 sqlmap")
    assert r["records"] == []


@pytest.mark.asyncio
async def test_list_q_blank_is_not_a_filter():
    es = FakeSearchES([_doc_text("a", "t", "s")])
    r = await analysis_store.list_records(None, 50, None, None, es=es, q="   ")
    assert [x["id"] for x in r["records"]] == ["a"]
    assert not any("simple_query_string" in f for f in es.last_body["query"]["bool"]["filter"])


@pytest.mark.asyncio
async def test_list_since_narrows_window():
    now = time.time()
    es = FakeSearchES([
        _doc("recent", None, created_at=now - 60),
        _doc("older", None, created_at=now - 3600),
    ])
    r = await analysis_store.list_records(None, 50, None, None, es=es, since=now - 600)
    assert [x["id"] for x in r["records"]] == ["recent"]


@pytest.mark.asyncio
async def test_since_cannot_reach_past_the_ttl_floor():
    """TTL 是硬下界 —— since 只能收窄窗口，不能把过期记录放回来。"""
    now = time.time()
    ttl = analysis_store._ttl_seconds()
    es = FakeSearchES([_doc("expired", None, created_at=now - ttl - 3600)])
    r = await analysis_store.list_records(None, 50, None, None, es=es, since=0)
    assert r["records"] == []
    gte = es.last_body["query"]["bool"]["filter"][0]["range"]["created_at"]["gte"]
    assert gte > now - ttl - 1
