"""Wiring of the solutions store into the query endpoints.

The store is an accelerator, never a dependency: recording happens off the
response path, retrieval degrades to "no examples", and neither may break a
search. These tests pin that down at the route level — the store itself is
covered by test_solutions.py.
"""
import asyncio
import os
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent  # .../poc
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

os.environ.pop("RST_GATEWAY_SHARED_SECRET", None)
os.environ.pop("RST_ADMIN_TOKEN", None)

from fastapi.testclient import TestClient  # noqa: E402

import pytest  # noqa: E402

from backend import license_state, main, solutions  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_failed_cases(monkeypatch, tmp_path):
    """/api/feedback appends to poc/eval/failed_cases.yaml — a real, tracked
    repo file. Point it at a tmp path so running the suite doesn't dirty it."""
    monkeypatch.setattr(main, "_FAILED_CASES_PATH", tmp_path / "failed_cases.yaml")


@pytest.fixture(autouse=True)
def _licensed(monkeypatch):
    """Answer the license gate directly.

    Two reasons, both about isolation: the gate 403s every /api/* call once
    some earlier test in the session has left the state at heartbeat_lost, and
    entering TestClient as a context manager would run app startup — including
    a heartbeat — which is what flips that state for everyone after us. So:
    patch the state, and construct the client WITHOUT the context manager.
    """
    monkeypatch.setattr(
        license_state, "get_state",
        lambda: {"status": license_state.STATUS_VALID, "features": ["*"]},
    )

_DSL = {"query": {"match_all": {}}, "size": 5}


def _es_result(hits: int):
    return {"took": 1, "hits": {"total": {"value": hits, "relation": "eq"}, "hits": []}}


def _stub_execute(monkeypatch, hits: int, recorded: list):
    async def fake_search(index, dsl):
        return _es_result(hits)

    async def fake_record(**kw):
        recorded.append(kw)
        return "id"

    monkeypatch.setattr(main, "_check_index", lambda *a, **k: None)
    monkeypatch.setattr(main, "execute_search", fake_search)
    monkeypatch.setattr(solutions, "record_success", fake_record)


def test_execute_records_a_question_that_returned_hits(monkeypatch):
    recorded: list = []
    _stub_execute(monkeypatch, hits=42, recorded=recorded)
    client = TestClient(main.app)
    r = client.post("/api/execute", json={"index": "logs-*", "dsl": _DSL, "question": "谁登录失败了"})
    assert r.status_code == 200
    assert len(recorded) == 1
    assert recorded[0]["question"] == "谁登录失败了"
    assert recorded[0]["hits"] == 42
    assert recorded[0]["dsl"] == _DSL


def test_a_viewer_success_is_not_recorded(monkeypatch):
    """只读账号能查，但它的查询不进 few-shot 语料库。

    这库是喂给 NL→DSL 生成的「已验证示例」，写入权等于影响别人（含管理员）
    的生成结果 —— viewer 不该有。
    """
    from backend import user_db

    recorded: list = []
    _stub_execute(monkeypatch, hits=42, recorded=recorded)
    # 角色是每个请求现查的（user_db.role_of），不是会话里存的那个。
    monkeypatch.setattr(user_db, "role_of", lambda _name: "viewer")
    client = TestClient(main.app)
    r = client.post("/api/execute", json={"index": "logs-*", "dsl": _DSL, "question": "q"})
    assert r.status_code == 200          # 查还是能查
    assert recorded == []                # 但不录


def test_retrieval_is_scoped_to_the_caller(monkeypatch):
    """召回示例时带上 owner —— 别人的例子不进我的 few-shot。"""
    seen: list = []

    async def fake_find(question, index, top_k=3, owner=None):
        seen.append(owner)
        return []

    async def fake_recent(owner, within_s=300, limit=10):
        return []

    monkeypatch.setattr(solutions, "find_similar", fake_find)
    monkeypatch.setattr(solutions, "recent_questions", fake_recent)

    asyncio.run(main._solution_examples("q", "logs-*", "alice"))

    assert seen == ["alice"]


def test_execute_without_a_question_records_nothing(monkeypatch):
    recorded: list = []
    _stub_execute(monkeypatch, hits=42, recorded=recorded)
    client = TestClient(main.app)
    r = client.post("/api/execute", json={"index": "logs-*", "dsl": _DSL})
    assert r.status_code == 200
    assert recorded == []


def test_execute_with_zero_hits_records_nothing(monkeypatch):
    """A query that matched nothing is not a worked example."""
    recorded: list = []
    _stub_execute(monkeypatch, hits=0, recorded=recorded)
    client = TestClient(main.app)
    r = client.post("/api/execute", json={"index": "logs-*", "dsl": _DSL, "question": "q"})
    assert r.status_code == 200
    assert recorded == []


def test_execute_still_answers_when_recording_blows_up(monkeypatch):
    async def fake_search(index, dsl):
        return _es_result(7)

    async def boom(**kw):
        raise RuntimeError("solutions index down")

    monkeypatch.setattr(main, "_check_index", lambda *a, **k: None)
    monkeypatch.setattr(main, "execute_search", fake_search)
    monkeypatch.setattr(solutions, "record_success", boom)
    client = TestClient(main.app)
    r = client.post("/api/execute", json={"index": "logs-*", "dsl": _DSL, "question": "q"})
    assert r.status_code == 200
    assert r.json()["hits"]["total"]["value"] == 7


def test_thumbs_down_retires_the_example_by_question(monkeypatch):
    rejected: list = []

    async def fake_reject(question, index, owner, reason):
        rejected.append((question, index, reason))
        return 1

    monkeypatch.setattr(solutions, "reject_by_question", fake_reject)
    client = TestClient(main.app)
    r = client.post("/api/feedback", json={
        "question": "谁登录失败了", "index": "logs-*", "dsl": _DSL,
        "correct": False, "comment": "错的",
    })
    assert r.status_code == 200
    assert rejected and rejected[0][0] == "谁登录失败了"
    assert rejected[0][2] == "thumbs_down"


def test_thumbs_up_retires_nothing(monkeypatch):
    rejected: list = []

    async def fake_reject(question, index, owner, reason):
        rejected.append(question)
        return 1

    monkeypatch.setattr(solutions, "reject_by_question", fake_reject)
    client = TestClient(main.app)
    r = client.post("/api/feedback", json={
        "question": "q", "index": "logs-*", "dsl": _DSL, "correct": True,
    })
    assert r.status_code == 200
    assert rejected == []


def test_repeat_ask_retires_the_earlier_answer(monkeypatch):
    """A rephrasing within the window is the failure signal nobody clicks."""
    retired: list = []
    filed: list = []

    async def fake_recent(owner, within_s=300, limit=10):
        return [{"question": "登录失败的事件", "index": "logs-*", "rejected": False}]

    async def fake_reject(question, index, owner, reason):
        retired.append((question, reason))
        return 1

    async def fake_append(record):
        filed.append(record)

    monkeypatch.setattr(solutions, "recent_questions", fake_recent)
    monkeypatch.setattr(solutions, "reject_by_question", fake_reject)
    monkeypatch.setattr(main, "_append_failed_case", fake_append)

    asyncio.run(main._flag_repeat_ask("哪些账号登录失败了", "logs-*", "u"))

    assert retired == [("登录失败的事件", "repeat_ask")]
    assert filed and filed[0]["signal"] == "repeat_ask"
    assert filed[0]["correct"] is False


def test_an_unrelated_question_is_not_a_repeat(monkeypatch):
    retired: list = []

    async def fake_recent(owner, within_s=300, limit=10):
        return [{"question": "登录失败的事件", "index": "logs-*", "rejected": False}]

    async def fake_reject(question, index, owner, reason):
        retired.append(question)
        return 1

    monkeypatch.setattr(solutions, "recent_questions", fake_recent)
    monkeypatch.setattr(solutions, "reject_by_question", fake_reject)
    asyncio.run(main._flag_repeat_ask("磁盘空间不足的告警", "logs-*", "u"))
    assert retired == []


def test_an_already_rejected_prior_is_not_retired_twice(monkeypatch):
    retired: list = []

    async def fake_recent(owner, within_s=300, limit=10):
        return [{"question": "登录失败的事件", "index": "logs-*", "rejected": True}]

    async def fake_reject(question, index, owner, reason):
        retired.append(question)
        return 1

    monkeypatch.setattr(solutions, "recent_questions", fake_recent)
    monkeypatch.setattr(solutions, "reject_by_question", fake_reject)
    asyncio.run(main._flag_repeat_ask("哪些账号登录失败了", "logs-*", "u"))
    assert retired == []


def test_generate_hands_retrieval_a_string_owner(monkeypatch):
    """`/api/generate` 传给召回的必须是 owner 字符串，不是 `current_user()` 的 dict。

    传 dict 时 ES 回 `[term] query does not support [username]`，异常被 best-effort
    吞掉 —— few-shot 召回和「改口重问」信号双双静默失效，界面上什么都看不出来。
    写入侧（/api/execute）早就修成字符串了，读取侧漏了一处。
    """
    seen: list = []

    async def fake_find(question, index, top_k=3, owner=None):
        seen.append(owner)
        return []

    async def fake_recent(owner, within_s=300, limit=10):
        seen.append(owner)
        return []

    async def fake_mapping(index):
        return {"idx": {"mappings": {"properties": {"user.name": {"type": "keyword"}}}}}

    async def fake_samples(index):
        return {}

    async def fake_generate(question, index, mapping, **kwargs):
        return ({"query": {"match_all": {}}, "size": 5}, "ok", "high", None, None)

    monkeypatch.setattr(main, "_check_index", lambda *a, **k: None)
    monkeypatch.setattr(main, "get_mapping", fake_mapping)
    monkeypatch.setattr(main, "sample_values_for_prompt", fake_samples)
    monkeypatch.setattr(main, "generate_dsl", fake_generate)
    monkeypatch.setattr(solutions, "find_similar", fake_find)
    monkeypatch.setattr(solutions, "recent_questions", fake_recent)
    main.response_cache.clear()

    client = TestClient(main.app)
    r = client.post("/api/generate", json={"question": "谁登录失败了", "index": "logs-*"})
    assert r.status_code == 200, r.text
    assert seen, "召回一次都没被调用"
    assert all(isinstance(o, str) for o in seen), seen
