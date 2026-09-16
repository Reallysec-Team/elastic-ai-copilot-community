"""Wiring of correction capture into the query + feedback endpoints.

Capture is admin-gated (knowledge-base text steers every prompt, same reason
/api/kb/upload is), runs off the response path, and must never be able to
break an answer. The distilling itself is covered by test_corrections.py.
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

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import corrections, license_state, main, solutions  # noqa: E402

_DSL = {"query": {"match_all": {}}, "size": 5}
_PRIOR = [{"question": "转账失败的记录", "dsl": _DSL, "explanation": ""}]


@pytest.fixture(autouse=True)
def _isolated_failed_cases(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "_FAILED_CASES_PATH", tmp_path / "failed_cases.yaml")


@pytest.fixture(autouse=True)
def _licensed(monkeypatch):
    """See test_solutions_wiring: the gate 403s once an earlier test in the
    session has left the license at heartbeat_lost."""
    monkeypatch.setattr(
        license_state, "get_state",
        lambda: {"status": license_state.STATUS_VALID, "features": ["*"]},
    )


@pytest.fixture
def captured(monkeypatch):
    calls: list = []

    async def fake_capture(**kw):
        calls.append(kw)
        return "doc"

    monkeypatch.setattr(corrections, "capture", fake_capture)
    return calls


def _admin(monkeypatch, yes: bool):
    monkeypatch.setattr(main, "is_admin", lambda _r: yes)


class _Req:
    """Stand-in request. current_user() reads the session cookie now, so a bare
    object() no longer satisfies the one attribute this path touches."""

    cookies: dict[str, str] = {}
    headers: dict[str, str] = {}


def _capture_in_loop(*args) -> None:
    """Call the sync helper inside a running loop.

    `fire_and_forget` schedules onto the running loop and gives up (with a
    warning) when there isn't one — so calling the helper bare would leave the
    fake un-run and every assertion vacuously true.
    """
    async def _main():
        main._capture_correction(*args)
        await asyncio.sleep(0)  # let the scheduled task run

    asyncio.run(_main())


# ── the inline path: a correction typed as the next chat message ────────────


def test_a_correction_mid_conversation_is_captured(monkeypatch, captured):
    _admin(monkeypatch, True)
    _capture_in_loop("不对，转账失败要看 event_type=7", "logs-*", _PRIOR, _Req())
    assert len(captured) == 1
    assert captured[0]["correction"] == "不对，转账失败要看 event_type=7"
    # The thing being corrected is the PRIOR turn, not this message.
    assert captured[0]["question"] == "转账失败的记录"
    assert captured[0]["dsl"] == _DSL


def test_an_ordinary_question_costs_no_llm_call(monkeypatch, captured):
    """The lexical gate exists so the 99% never reach the distiller."""
    _admin(monkeypatch, True)
    _capture_in_loop("最近 30 天登录失败的事件", "logs-*", _PRIOR, _Req())
    assert captured == []


def test_the_first_message_of_a_conversation_corrects_nothing(monkeypatch, captured):
    _admin(monkeypatch, True)
    _capture_in_loop("不对，应该看 event_type=7", "logs-*", [], _Req())
    assert captured == []


def test_a_non_admin_correction_is_not_captured(monkeypatch, captured):
    """Same boundary as /api/kb/upload — KB text steers every prompt."""
    _admin(monkeypatch, False)
    _capture_in_loop("不对，转账失败要看 event_type=7", "logs-*", _PRIOR, _Req())
    assert captured == []


# ── the explicit path: the thumbs-down comment box ──────────────────────────


def _post_feedback(client, **over):
    body = {
        "question": "转账失败的记录", "index": "logs-*", "dsl": _DSL,
        "correct": False, "comment": "转账失败对应 event_type=7",
    }
    body.update(over)
    return client.post("/api/feedback", json=body)


def test_thumbs_down_comment_is_captured_ungated(monkeypatch, captured):
    """The comment box is already an explicit 'this was wrong', so the text
    need not contain a correction marker — note gated=False."""
    _admin(monkeypatch, True)
    monkeypatch.setattr(solutions, "reject_by_question", _noop_reject)
    r = _post_feedback(TestClient(main.app))
    assert r.status_code == 200
    assert len(captured) == 1
    assert captured[0]["correction"] == "转账失败对应 event_type=7"
    assert captured[0]["gated"] is False


def test_thumbs_down_without_a_comment_captures_nothing(monkeypatch, captured):
    _admin(monkeypatch, True)
    monkeypatch.setattr(solutions, "reject_by_question", _noop_reject)
    r = _post_feedback(TestClient(main.app), comment="   ")
    assert r.status_code == 200
    assert captured == []


def test_thumbs_up_captures_nothing(monkeypatch, captured):
    _admin(monkeypatch, True)
    monkeypatch.setattr(solutions, "reject_by_question", _noop_reject)
    r = _post_feedback(TestClient(main.app), correct=True, comment="很好")
    assert r.status_code == 200
    assert captured == []


def test_a_non_admin_comment_is_not_captured(monkeypatch, captured):
    _admin(monkeypatch, False)
    monkeypatch.setattr(solutions, "reject_by_question", _noop_reject)
    r = _post_feedback(TestClient(main.app))
    assert r.status_code == 200
    assert captured == []


def test_feedback_still_succeeds_when_capture_blows_up(monkeypatch):
    """Capture is an accelerator; a 👎 that reports failure because the KB is
    down would tell the analyst their correction was lost when it wasn't."""
    _admin(monkeypatch, True)
    monkeypatch.setattr(solutions, "reject_by_question", _noop_reject)

    async def boom(**kw):
        raise RuntimeError("kb down")

    monkeypatch.setattr(corrections, "capture", boom)
    r = _post_feedback(TestClient(main.app))
    assert r.status_code == 200


async def _noop_reject(question, index, owner, reason):
    return 0
