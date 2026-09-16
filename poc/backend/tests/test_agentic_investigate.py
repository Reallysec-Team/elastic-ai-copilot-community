"""Stage 4 — agentic investigate tool-use loop.

Drives the loop with a scripted fake router (no real LLM) and a fake
execute_search (no real ES), asserting: the loop runs es_search then finalizes,
guardrails (whitelist / validator / size-cap) gate every tool call, the step cap
forces a tool-less final, and an unparseable final degrades gracefully.
"""
from __future__ import annotations

import pytest
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import agentic_investigate as ag  # noqa: E402
from conftest import premium_core  # noqa: E402
from backend.index_whitelist import IndexWhitelist  # noqa: E402

_FINAL_JSON = (
    '{"summary":"暴力破解成功","alert_type":"暴力破解","severity":"high",'
    '"confidence":"high","recommended_actions":["封禁源 IP"]}'
)


# ── fake LLM response builders ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _needs_sealed_core():
    """这个文件测的是密封内核驱动的能力；没有 premium_src 的 checkout 里整文件 skip。"""
    premium_core("alert_investigation")


def _tool_call(cid, name, args_json):
    return SimpleNamespace(
        id=cid, type="function",
        function=SimpleNamespace(name=name, arguments=args_json),
    )


def _resp(content=None, tool_calls=None, total_tokens=0):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg)],
        usage=SimpleNamespace(total_tokens=total_tokens),
    )


class _FakeRouter:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return self._scripted.pop(0), SimpleNamespace(id="fake")


def _install(monkeypatch, scripted, whitelist_patterns=None, es_hits=None, seed_hits=None):
    router = _FakeRouter(scripted)
    monkeypatch.setattr(ag, "get_router", lambda: router)
    monkeypatch.setattr(
        ag.index_whitelist, "get",
        lambda: IndexWhitelist(whitelist_patterns or []),
    )

    # Stub the pre-fetch seed so tests stay hermetic (no real ES). Default: no
    # seed, so the loop behaves as before unless a test opts in.
    async def _fake_seed(alert_src, index, window_minutes):
        return list(seed_hits or [])

    monkeypatch.setattr(ag, "_gather_context", _fake_seed)
    executed = []

    async def _fake_execute(index, dsl):
        executed.append({"index": index, "dsl": dsl})
        hits = es_hits if es_hits is not None else [
            {"_id": "h1", "_source": {"msg": "failed login"}},
        ]
        return {"hits": {"hits": hits}}

    monkeypatch.setattr(ag, "execute_search", _fake_execute)
    # Keep masking a no-op so assertions read the raw shape.
    monkeypatch.setattr(ag, "mask_doc", lambda d: d)
    return router, executed


_ALERT = {"_source": {"src_ip": "1.2.3.4", "event": "auth_failure"}}


def _run(alert, index, **kw):
    return asyncio.run(ag.agentic_investigate_alert(alert, index, **kw))


def test_loop_runs_tool_then_finalizes(monkeypatch):
    scripted = [
        _resp(tool_calls=[_tool_call("c1", "es_search",
              '{"index":"logs-auth","dsl":{"query":{"match_all":{}}}}')]),
        _resp(content=_FINAL_JSON),
    ]
    _router, executed = _install(monkeypatch, scripted, ["logs-*"])
    result = _run(_ALERT, "logs-auth", max_steps=4)

    assert result["degraded"] is False
    assert result["agentic"] is True
    assert result["summary"] == "暴力破解成功"
    assert result["severity"] == "high"
    assert result["agentic_steps"] == 1
    assert result["context_count"] == 1        # one masked hit seen
    assert len(executed) == 1
    assert executed[0]["index"] == "logs-auth"


def test_seed_context_injected_and_counted(monkeypatch):
    # With a pre-fetched seed the model has real (masked) evidence up front and
    # can finalize WITHOUT issuing an es_search (which would query masked values
    # and return nothing in cloud/private masking).
    scripted = [_resp(content=_FINAL_JSON)]  # finalize immediately, no tool call
    router, executed = _install(
        monkeypatch, scripted, ["logs-*"],
        seed_hits=[{"_id": "s1", "_source": {"src_ip": "1.2.3.4", "msg": "seed evt"}}],
    )
    result = _run(_ALERT, "logs-auth", max_steps=4)

    assert result["degraded"] is False
    assert executed == []                       # no blind query needed
    assert result["context_count"] == 1         # seed counted as context
    user_msg = next(
        m for c in router.calls for m in c["messages"] if m.get("role") == "user"
    )
    assert "初始证据" in user_msg["content"]      # seed block injected
    assert "seed evt" in user_msg["content"]     # real evidence reached the model


def test_blocked_index_never_hits_es(monkeypatch):
    scripted = [
        _resp(tool_calls=[_tool_call("c1", "es_search",
              '{"index":".security-7","dsl":{"query":{"match_all":{}}}}')]),
        _resp(content=_FINAL_JSON),
    ]
    _router, executed = _install(monkeypatch, scripted, ["logs-*"])
    result = _run(_ALERT, "logs-auth", max_steps=4)

    assert executed == []                       # guardrail blocked it pre-ES
    assert "白名单" in (result["tool_trace"][0]["error"] or "")
    assert result["degraded"] is False          # model still produced a verdict


def test_forbidden_dsl_rejected(monkeypatch):
    scripted = [
        _resp(tool_calls=[_tool_call("c1", "es_search",
              '{"index":"logs-auth","dsl":{"script":{"source":"evil"}}}')]),
        _resp(content=_FINAL_JSON),
    ]
    _router, executed = _install(monkeypatch, scripted, ["logs-*"])
    result = _run(_ALERT, "logs-auth", max_steps=4)

    assert executed == []
    assert "DSL" in (result["tool_trace"][0]["error"] or "")


def test_size_cap_clamped(monkeypatch):
    scripted = [
        _resp(tool_calls=[_tool_call("c1", "es_search",
              '{"index":"logs-auth","dsl":{"query":{"match_all":{}},"size":9999}}')]),
        _resp(content=_FINAL_JSON),
    ]
    monkeypatch.setenv("RST_AGENTIC_SIZE_CAP", "20")
    _router, executed = _install(monkeypatch, scripted, ["logs-*"])
    _run(_ALERT, "logs-auth", max_steps=4)

    assert executed[0]["dsl"]["size"] == 20     # clamped from 9999


def test_step_cap_forces_toolless_final(monkeypatch):
    # Model keeps asking for tools; after max_steps we force a final with
    # tool_choice="none".
    tc = _resp(tool_calls=[_tool_call("c1", "es_search",
               '{"index":"logs-auth","dsl":{"query":{"match_all":{}}}}')])
    scripted = [tc, tc, _resp(content=_FINAL_JSON)]  # 2 loop steps + forced final
    router, executed = _install(monkeypatch, scripted, ["logs-*"])
    result = _run(_ALERT, "logs-auth", max_steps=2)

    assert result["degraded"] is False
    assert result["agentic_steps"] == 2
    assert len(executed) == 2
    assert router.calls[-1]["tool_choice"] == "none"   # forced tool-less final


def test_unparseable_final_degrades(monkeypatch):
    scripted = [_resp(content="这不是 JSON，随便说点什么")]
    _router, _executed = _install(monkeypatch, scripted, ["logs-*"])
    result = _run(_ALERT, "logs-auth", max_steps=4)

    assert result["degraded"] is True
    assert result["agentic"] is True


# ── Stage 5: production hardening ───────────────────────────────────────────

def test_tool_returns_masked_aggregations(monkeypatch):
    scripted = [
        _resp(tool_calls=[_tool_call("c1", "es_search",
              '{"index":"logs-auth","dsl":{"size":0,'
              '"aggs":{"top_users":{"terms":{"field":"user.name"}}}}}')]),
        _resp(content=_FINAL_JSON),
    ]
    # Real masking (cloud) so we prove the agg key is masked end-to-end.
    monkeypatch.setenv("RST_MASKING_MODE", "cloud")
    router = _FakeRouter(scripted)
    monkeypatch.setattr(ag, "get_router", lambda: router)
    monkeypatch.setattr(ag.index_whitelist, "get", lambda: IndexWhitelist(["logs-*"]))

    async def _fake_execute(index, dsl):
        return {
            "hits": {"hits": []},
            "aggregations": {
                "top_users": {"buckets": [{"key": "administrator", "doc_count": 9}]}
            },
        }

    monkeypatch.setattr(ag, "execute_search", _fake_execute)
    _run(_ALERT, "logs-auth", max_steps=4)

    # The tool-result message fed back to the model must carry the MASKED key.
    tool_msg = next(
        m for c in router.calls for m in c["messages"] if m.get("role") == "tool"
    )
    assert "administrator" not in tool_msg["content"]
    assert "a***r" in tool_msg["content"]
    assert '"doc_count": 9' in tool_msg["content"]   # count preserved


def test_provider_without_tools_falls_back_to_single_step(monkeypatch):
    # A provider that can't do function-calling makes the FIRST tool call raise.
    # We should degrade to the non-agentic single-step path, not 500.
    class _BoomRouter:
        def __init__(self):
            self.calls = []

        async def chat_completion(self, **kwargs):
            self.calls.append(kwargs)
            raise RuntimeError("this model does not support tools")

    monkeypatch.setattr(ag, "get_router", lambda: _BoomRouter())
    monkeypatch.setattr(
        ag.index_whitelist, "get", lambda: IndexWhitelist(["logs-*"])
    )
    called = {"single": False}

    async def _fake_single(alert, index, window_minutes=30, progress=None):
        called["single"] = True
        return {"summary": "single-step 兜底", "agentic": False, "degraded": False}

    monkeypatch.setattr(ag, "investigate_alert", _fake_single)
    result = _run(_ALERT, "logs-auth", max_steps=4)

    assert called["single"] is True
    assert result["summary"] == "single-step 兜底"


def test_token_budget_forces_early_final(monkeypatch):
    # Model would keep searching, but the token budget trips after step 1 and we
    # force a tool-less final rather than burning the full step budget.
    tc = _resp(
        tool_calls=[_tool_call("c1", "es_search",
                    '{"index":"logs-auth","dsl":{"query":{"match_all":{}}}}')],
        total_tokens=100,
    )
    scripted = [tc, _resp(content=_FINAL_JSON)]  # step1 + forced final only
    monkeypatch.setenv("RST_AGENTIC_TOKEN_BUDGET", "50")
    router, executed = _install(monkeypatch, scripted, ["logs-*"])
    result = _run(_ALERT, "logs-auth", max_steps=6)   # high step cap on purpose

    assert result["degraded"] is False
    assert result["agentic_steps"] == 1               # budget stopped it at 1
    assert len(executed) == 1
    assert len(router.calls) == 2                     # step1 + forced final
    assert router.calls[-1]["tool_choice"] == "none"


def test_agentic_enabled_default_on(monkeypatch):
    monkeypatch.delenv("RST_AGENTIC_INVESTIGATE", raising=False)
    assert ag.agentic_enabled() is True


def test_agentic_enabled_explicit_off(monkeypatch):
    for off in ("0", "false", "no", "off", "OFF"):
        monkeypatch.setenv("RST_AGENTIC_INVESTIGATE", off)
        assert ag.agentic_enabled() is False


def test_deadline_defaults_to_180(monkeypatch):
    monkeypatch.delenv("RST_AGENTIC_DEADLINE_S", raising=False)
    assert ag._deadline_s() == 180.0
    monkeypatch.setenv("RST_AGENTIC_DEADLINE_S", "0")   # explicit disable
    assert ag._deadline_s() == 0.0


def test_deadline_exceeded_degrades(monkeypatch):
    import asyncio as _aio

    class _SlowRouter:
        calls = []

        async def chat_completion(self, **kwargs):
            await _aio.sleep(1.0)
            return _resp(content=_FINAL_JSON), SimpleNamespace(id="x")

    monkeypatch.setattr(ag, "get_router", lambda: _SlowRouter())
    monkeypatch.setattr(
        ag.index_whitelist, "get", lambda: IndexWhitelist(["logs-*"])
    )
    monkeypatch.setattr(ag, "mask_doc", lambda d: d)
    monkeypatch.setenv("RST_AGENTIC_DEADLINE_S", "0.05")
    result = _run(_ALERT, "logs-auth", max_steps=4)

    assert result["degraded"] is True
    assert result["agentic"] is True
    assert result["agentic_steps"] == 0


# ── tool 参数的容错解析 ────────────────────────────────────────────────────
# 实测：一次 6 轮的 agentic 调查里有 2 轮废在 "tool arguments are not valid
# JSON" 上 —— 模型把参数裹进了 ```json 围栏。步数上限本来就小，两次白跑等于丢掉
# 三分之一的调查预算，所以这里就地修，而不是再让模型转一圈。


def test_parse_tool_args_plain_json():
    assert ag._parse_tool_args('{"index": "logs-*", "dsl": {}}') == {
        "index": "logs-*",
        "dsl": {},
    }


def test_parse_tool_args_empty_means_no_args():
    assert ag._parse_tool_args("") == {}
    assert ag._parse_tool_args("   ") == {}


def test_parse_tool_args_strips_json_fence():
    raw = '```json\n{"index": "logs-*", "dsl": {"query": {"match_all": {}}}}\n```'
    assert ag._parse_tool_args(raw)["index"] == "logs-*"


def test_parse_tool_args_strips_bare_fence():
    assert ag._parse_tool_args('```\n{"index": "a"}\n```') == {"index": "a"}


def test_parse_tool_args_recovers_object_from_prose():
    raw = 'Sure, here are the arguments: {"index": "logs-*", "dsl": {}} — hope this helps'
    assert ag._parse_tool_args(raw)["index"] == "logs-*"


def test_parse_tool_args_gives_up_on_garbage():
    assert ag._parse_tool_args("not json at all") is None
    assert ag._parse_tool_args("{oops") is None

# ── 检索时间窗必须锚在告警时间上 ──────────────────────────────────────────
# 实测：一条 6.5 小时前的告警，模型 4 轮全部用 now-30m / now-2h 检索，0 命中，
# 结论写成「未找到关联原始日志」—— 日志一直在那儿。提示词里那句「最近 30 分钟」
# 就是在教模型写 now-。


def test_agentic_prompt_uses_absolute_window_when_bounds_given():
    from backend.prompts import build_agentic_investigate_prompt

    p = build_agentic_investigate_prompt(
        {"host": {"name": "web-prod-03"}},
        "logs-*",
        30,
        ["logs-*"],
        {"gte": "2026-09-05T23:16:17Z", "lte": "2026-09-06T00:16:17Z"},
    )
    assert "2026-09-05T23:16:17Z" in p
    assert "2026-09-06T00:16:17Z" in p
    assert "now-30m" in p  # 出现在「不要这么写」那句里
    assert "不要用" in p


def test_agentic_prompt_falls_back_to_relative_window():
    from backend.prompts import build_agentic_investigate_prompt

    p = build_agentic_investigate_prompt({}, "logs-*", 45, ["logs-*"])
    assert "最近 45 分钟" in p

def test_parse_tool_args_keeps_first_object_when_stream_repeats_a_slice():
    """实测到的那种坏参数：一个完整对象后面又粘了自己中间的一段。

    流式 tool_call 的 arguments 是一片片累加起来的，累重了就成这样。整串 loads
    不过，但第一个对象本身是好的 —— 那就是模型的意思，后面是累加的碎屑。
    """
    good = '{"index": "logs-*", "dsl": {"size": 50}}'
    raw = good + ', {"term": {"host.name": "web-prod-03"}}], "sort": [{"@timestamp": "asc"}]}}}'
    assert ag._parse_tool_args(raw) == {"index": "logs-*", "dsl": {"size": 50}}
