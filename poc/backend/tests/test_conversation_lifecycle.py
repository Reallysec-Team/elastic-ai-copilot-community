"""轮次生命周期：open(pending) → settle(done/failed/aborted)，reap 收 pending 超时 +
删空壳，给模型的历史只含成功轮次。内存后端直接跑；ES 后端用假 ES 走同一套断言。"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import conversation as conv  # noqa: E402


@pytest.fixture(autouse=True)
def _mem(monkeypatch):
    monkeypatch.delenv("RST_CONVERSATION_BACKEND", raising=False)
    conv._store.clear()
    yield
    conv._store.clear()


def _run(coro):
    return asyncio.run(coro)


# ── 内存后端 ────────────────────────────────────────────────────────────────

def test_open_creates_conversation_with_first_turn_pending():
    cid, tid = _run(conv.open_turn(None, {"question": "q1", "index": "idx"}))
    entry = _run(conv.get(cid))
    assert entry and len(entry["turns"]) == 1
    t = entry["turns"][0]
    assert t["turn_id"] == tid and t["status"] == "pending" and t["question"] == "q1"


def test_settle_done_fills_dsl_and_keeps_order():
    cid, tid = _run(conv.open_turn(None, {"question": "q1", "index": "idx"}))
    _run(conv.settle_turn(cid, tid, conv.TURN_DONE, {"dsl": {"size": 1}, "explanation": "ok"}))
    cid2, tid2 = _run(conv.open_turn(cid, {"question": "q2", "index": "idx"}))
    assert cid2 == cid
    turns = _run(conv.get(cid))["turns"]
    assert [t["status"] for t in turns] == ["done", "pending"]
    assert turns[0]["dsl"] == {"size": 1}


def test_failed_and_aborted_turns_stay_in_history_but_not_in_prompt():
    cid, t1 = _run(conv.open_turn(None, {"question": "q1", "index": "idx"}))
    _run(conv.settle_turn(cid, t1, conv.TURN_FAILED, {"error": {"code": "x", "message": "boom"}}))
    _, t2 = _run(conv.open_turn(cid, {"question": "q2", "index": "idx"}))
    _run(conv.settle_turn(cid, t2, conv.TURN_ABORTED))
    _, t3 = _run(conv.open_turn(cid, {"question": "q3", "index": "idx"}))
    _run(conv.settle_turn(cid, t3, conv.TURN_DONE, {"dsl": {"size": 3}}))
    turns = _run(conv.get(cid))["turns"]
    assert [t["status"] for t in turns] == ["failed", "aborted", "done"]
    assert turns[0]["error"]["message"] == "boom"
    # 失败 / 中断的不喂给模型
    assert [t["question"] for t in conv.turns_for_prompt(turns)] == ["q3"]


def test_settle_bad_status_rejected():
    cid, tid = _run(conv.open_turn(None, {"question": "q", "index": "i"}))
    with pytest.raises(ValueError):
        _run(conv.settle_turn(cid, tid, "weird"))


def test_open_ignores_foreign_conversation_and_starts_fresh():
    cid, _ = _run(conv.open_turn(None, {"question": "q", "index": "i"}, owner="alice"))
    cid2, _ = _run(conv.open_turn(cid, {"question": "q2", "index": "i"}, owner="bob"))
    assert cid2 != cid
    assert len(_run(conv.get(cid, owner="alice"))["turns"]) == 1


def test_summary_carries_last_status_and_no_empty_conversations():
    cid, tid = _run(conv.open_turn(None, {"question": "q", "index": "i"}))
    _run(conv.settle_turn(cid, tid, conv.TURN_FAILED, {"error": {"code": "x", "message": "m"}}))
    lst = _run(conv.list_all())
    assert lst["total"] == 1
    assert lst["conversations"][0]["turn_count"] == 1
    assert lst["conversations"][0]["last_status"] == "failed"


def test_reap_times_out_old_pending_and_deletes_empties():
    cid, tid = _run(conv.open_turn(None, {"question": "q", "index": "i"}))
    # 手工把它做旧 + 塞一个老版本留下的空壳
    conv._store[cid]["turns"][0]["timestamp"] = time.time() - conv.PENDING_STALE_S - 1
    conv._store["empty"] = {"id": "empty", "owner": None, "turns": [], "last_at": time.time(), "created_at": time.time()}
    fresh_cid, _ = _run(conv.open_turn(None, {"question": "fresh", "index": "i"}))
    out = _run(conv.reap_stale())
    assert out == {"timed_out": 1, "empties": 1}
    assert "empty" not in conv._store
    assert conv._store[cid]["turns"][0]["status"] == "failed"
    assert conv._store[cid]["turns"][0]["error"]["code"] == "turn_reaped"
    assert conv._store[fresh_cid]["turns"][0]["status"] == "pending"  # 新的不动


def test_legacy_turns_without_status_count_as_done():
    # 老记录（append_turn 时代）没有 status 字段，历史照旧喂给模型。
    assert conv.turns_for_prompt([{"question": "q", "dsl": {"a": 1}}]) == [{"question": "q", "dsl": {"a": 1}}]


# ── ES 后端（假 ES：get / index / update 带乐观并发；update_by_query 走 painless）──

class _Resp:
    def __init__(self, body):
        self.body = body


class _FakeES:
    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.seq: dict[str, int] = {}
        self.update_by_query_calls: list[dict] = []

    class indices:  # noqa: N801
        @staticmethod
        async def exists(index):  # noqa: A002
            return True

    async def get(self, index, id):  # noqa: A002
        from elasticsearch import NotFoundError
        if id not in self.docs:
            raise NotFoundError(404, "not found", {})
        return _Resp({"found": True, "_source": self.docs[id], "_seq_no": self.seq[id], "_primary_term": 1})

    async def index(self, index, id, document, refresh=None):  # noqa: A002
        self.docs[id] = dict(document)
        self.seq[id] = 0
        return _Resp({"result": "created"})

    async def update(self, index, id, doc, refresh=None, if_seq_no=None, if_primary_term=None):  # noqa: A002
        from elasticsearch import ConflictError
        if if_seq_no != self.seq[id]:
            raise ConflictError(409, "conflict", {})
        self.docs[id].update(doc)
        self.seq[id] += 1
        return _Resp({"result": "updated"})

    async def update_by_query(self, index, query, script, conflicts, refresh):  # noqa: A002
        self.update_by_query_calls.append({"query": query, "script": script})
        return _Resp({"updated": 2, "deleted": 1})


@pytest.fixture
def es(monkeypatch):
    fake = _FakeES()
    monkeypatch.setenv("RST_CONVERSATION_BACKEND", "es")
    monkeypatch.setattr("backend.es_client.get_es", lambda: fake)
    conv._reset_index_ready_for_tests()
    return fake


def test_es_open_writes_conversation_and_first_turn_in_one_doc(es):
    cid, tid = _run(conv.open_turn(None, {"question": "q", "index": "i"}))
    doc = es.docs[cid]
    assert len(doc["turns"]) == 1 and doc["turns"][0]["status"] == "pending"


def test_es_settle_updates_in_place_with_optimistic_concurrency(es):
    cid, tid = _run(conv.open_turn(None, {"question": "q", "index": "i"}))
    _run(conv.settle_turn(cid, tid, conv.TURN_DONE, {"dsl": {"size": 0}}))
    t = es.docs[cid]["turns"][0]
    assert t["status"] == "done" and t["dsl"] == {"size": 0} and "settled_at" in t
    assert es.seq[cid] == 1


def test_es_open_on_existing_appends_and_retains_window(es):
    cid, _ = _run(conv.open_turn(None, {"question": "q0", "index": "i"}))
    for n in range(1, conv.TURN_RETAIN + 2):
        _run(conv.open_turn(cid, {"question": f"q{n}", "index": "i"}))
    assert len(es.docs[cid]["turns"]) == conv.TURN_RETAIN


def test_es_reap_runs_one_painless_pass(es):
    out = _run(conv.reap_stale())
    assert out == {"timed_out": 2, "empties": 1}
    call = es.update_by_query_calls[0]
    src = call["script"]["source"]
    assert "ctx.op = 'delete'" in src and "params.cutoff" in src and "noop" in src
    assert call["script"]["params"]["status"] == "failed"
