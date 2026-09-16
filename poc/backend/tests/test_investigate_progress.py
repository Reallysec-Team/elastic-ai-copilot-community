"""档 1 — staged-progress SSE: assert both investigate paths emit stage markers
in the right order, and that a None sink (blocking callers) stays a no-op.

ponytail: mocks are scripted fakes (no real ES / LLM / RAG) — same style as
test_agentic_investigate.py. We assert the *sequence of stage keys*, not the
LLM content (that's covered elsewhere). Simplification: `_gather_context` /
`asset_context_block` / `augment_prompt_meta` are stubbed wholesale rather than
their ES/vector internals.
"""
from __future__ import annotations

import asyncio
import sys

import pytest
from pathlib import Path
from types import SimpleNamespace

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import agentic_investigate as ag  # noqa: E402
from conftest import premium_core  # noqa: E402
from backend import investigate as inv  # noqa: E402
from backend.index_whitelist import IndexWhitelist  # noqa: E402

_FINAL_JSON = (
    '{"summary":"暴力破解成功","alert_type":"暴力破解","severity":"high",'
    '"confidence":"high","recommended_actions":["封禁源 IP"]}'
)
_ALERT = {"_source": {"src_ip": "1.2.3.4", "event": "auth_failure"}}


@pytest.fixture(autouse=True)
def _needs_sealed_core():
    """这个文件测的是密封内核驱动的能力；没有 premium_src 的 checkout 里整文件 skip。"""
    premium_core("alert_investigation")


def _collector():
    events: list[dict] = []

    async def progress(evt: dict) -> None:
        events.append(evt)

    return events, progress


def _resp(content=None, tool_calls=None, total_tokens=0):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg)],
        usage=SimpleNamespace(total_tokens=total_tokens),
    )


class _FakeRouter:
    def __init__(self, scripted):
        self._scripted = list(scripted)

    async def chat_completion(self, **kwargs):
        return self._scripted.pop(0), SimpleNamespace(id="fake")


def _keys_in_order(events, status=None):
    return [e["key"] for e in events
            if e.get("type") == "stage" and (status is None or e["status"] == status)]


# ── non-agentic single-step path ────────────────────────────────────────────

def test_single_step_emits_stage_sequence(monkeypatch):
    async def _fake_gather(alert_src, index, window_minutes, top_n=12):
        return [{"_id": "h1", "_source": {"msg": "x"}}, {"_id": "h2", "_source": {}}]

    async def _fake_block(alert_src):
        return ""

    async def _fake_rag(prompt, top_k=5):
        return prompt, 3

    monkeypatch.setattr(inv, "_gather_context", _fake_gather)
    monkeypatch.setattr(inv, "asset_context_block", _fake_block)
    monkeypatch.setattr(inv, "augment_prompt_meta", _fake_rag)
    monkeypatch.setattr(inv, "mask_doc", lambda d: d)
    monkeypatch.setattr(inv, "get_router", lambda: _FakeRouter([_resp(content=_FINAL_JSON)]))

    events, progress = _collector()
    result = asyncio.run(inv.investigate_alert(_ALERT, "logs-auth", progress=progress))

    # done markers must arrive in pipeline order, analyze last (active, no done —
    # the SSE `result` frame is its completion).
    assert _keys_in_order(events, "done") == ["context", "enrich", "rag"]
    assert _keys_in_order(events)[-1] == "analyze"
    # detail carries the counts the checklist shows.
    ctx = next(e for e in events if e["key"] == "context" and e["status"] == "done")
    assert ctx["detail"] == "2 条"
    rag = next(e for e in events if e["key"] == "rag" and e["status"] == "done")
    assert rag["detail"] == "3 段"
    assert result["summary"] == "暴力破解成功"


def test_none_progress_is_noop(monkeypatch):
    async def _fake_gather(*a, **k):
        return []

    async def _fake_block(*a, **k):
        return ""

    async def _fake_rag(prompt, top_k=5):
        return prompt, 0

    monkeypatch.setattr(inv, "_gather_context", _fake_gather)
    monkeypatch.setattr(inv, "asset_context_block", _fake_block)
    monkeypatch.setattr(inv, "augment_prompt_meta", _fake_rag)
    monkeypatch.setattr(inv, "mask_doc", lambda d: d)
    monkeypatch.setattr(inv, "get_router", lambda: _FakeRouter([_resp(content=_FINAL_JSON)]))

    # No progress arg → must behave exactly like before (no crash, valid result).
    result = asyncio.run(inv.investigate_alert(_ALERT, "logs-auth"))
    assert result["degraded"] is False


# ── agentic tool-loop path ──────────────────────────────────────────────────

def _tool_call(cid, name, args_json):
    return SimpleNamespace(
        id=cid, type="function",
        function=SimpleNamespace(name=name, arguments=args_json),
    )


def test_agentic_emits_enrich_retrieve_analyze(monkeypatch):
    scripted = [
        _resp(tool_calls=[_tool_call("c1", "es_search",
              '{"index":"logs-auth","dsl":{"query":{"match_all":{}}}}')]),
        _resp(content=_FINAL_JSON),
    ]
    monkeypatch.setattr(ag, "get_router", lambda: _FakeRouter(scripted))
    monkeypatch.setattr(ag.index_whitelist, "get", lambda: IndexWhitelist(["logs-*"]))
    monkeypatch.setattr(ag, "mask_doc", lambda d: d)

    async def _fake_block(alert_src):
        return ""

    async def _fake_execute(index, dsl):
        return {"hits": {"hits": [{"_id": "h1", "_source": {"msg": "failed login"}}]}}

    monkeypatch.setattr(ag, "asset_context_block", _fake_block)
    monkeypatch.setattr(ag, "execute_search", _fake_execute)

    events, progress = _collector()
    result = asyncio.run(
        ag.agentic_investigate_alert(_ALERT, "logs-auth", progress=progress)
    )

    keys = _keys_in_order(events)
    assert "enrich" in keys and "retrieve" in keys and "analyze" in keys
    # enrich resolves before the first retrieval; analyze is the last stage.
    assert keys.index("enrich") < keys.index("retrieve") < keys.index("analyze")
    assert result["agentic"] is True


# ── H1: context window anchors on the alert's own timestamp, not now ─────────

def test_time_bounds_anchors_on_alert_timestamp():
    # A historical alert must gather context around WHEN it happened (symmetric
    # ±window), not now-window (which would return nothing for old data).
    b = inv._time_bounds({"@timestamp": "2026-04-30T10:00:00Z"}, 30)
    assert b["gte"] == "2026-04-30T09:30:00+00:00"
    assert b["lte"] == "2026-04-30T10:30:00+00:00"


def test_time_bounds_falls_back_to_now_without_timestamp():
    b = inv._time_bounds({"src_ip": "1.2.3.4"}, 30)  # no timestamp field
    assert b == {"gte": "now-30m"} and "lte" not in b


if __name__ == "__main__":  # pragma: no cover — allow `python test_...` too
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
