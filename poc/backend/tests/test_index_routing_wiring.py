"""索引自动路由接进 /api/generate 之后的行为。

不打真的 ES / LLM：候选清单、mapping、样例值、生成本身全部打桩。要证的是三件事：
  1. 请求不带 index 时，网关自己挑一个，并把挑的结果和理由回给前端；
  2. 请求带了 index 时，一个字都不改（用户的选择优先，也保住旧客户端）；
  3. 集群里一个可查索引都没有时，明说而不是猜一个。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from fastapi.testclient import TestClient  # noqa: E402

from backend import license_state, main as m  # noqa: E402

_MAPPING = {"idx": {"mappings": {"properties": {"user.name": {"type": "keyword"}}}}}

_INDICES = [
    {"name": "logs-nginx.access-default", "doc_count": 4830},
    {"name": "logs-linux.auth-default", "doc_count": 2182},
]


@pytest.fixture
def client(monkeypatch):
    # 全量跑时前面的 license 用例会把全局状态留在 heartbeat_lost 上，license 闸
    # 于是 403。和 test_alerts_stats / test_audit_summary 用同一个中和办法。
    monkeypatch.setattr(
        license_state, "get_state",
        lambda: {"status": license_state.STATUS_VALID, "features": ["*"]},
    )

    async def fake_list_indices(pattern=None, include_system=False):
        return {"total": len(_INDICES), "indices": _INDICES}

    async def fake_get_mapping(index):
        return _MAPPING

    async def fake_samples(index):
        return {}

    async def fake_examples(question, index, user):
        return []

    async def fake_generate(question, index, mapping, **kwargs):
        # 把网关最终选定的 index 原样回显在 explanation 里，测试据此断言。
        # 五元组：最后一位是 time_intent（问题里有没有明确说时间），这里的问题
        # 没提时间，所以是 None。
        return ({"query": {"match_all": {}}}, f"索引={index}", "high", None, None)

    monkeypatch.setattr(m, "list_indices", fake_list_indices)
    monkeypatch.setattr(m, "get_mapping", fake_get_mapping)
    monkeypatch.setattr(m, "sample_values_for_prompt", fake_samples)
    monkeypatch.setattr(m, "_solution_examples", fake_examples)
    monkeypatch.setattr(m, "generate_dsl", fake_generate)
    # 响应缓存会让第二个用例读到第一个用例的答案。
    m.response_cache.clear()
    return TestClient(m.app)


def _post(client, body):
    return client.post("/api/generate", json=body)


def test_missing_index_is_routed_from_the_question(client):
    r = _post(client, {"question": "最近 24 小时登录失败最多的账号"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["index"] == "logs-linux.auth-default"
    assert body["routing"]["source"] == "name"
    # 前端要显示「为什么查这里」，理由不能是空的。
    assert body["routing"]["reason"]
    assert body["explanation"] == "索引=logs-linux.auth-default"


def test_explicit_index_is_left_alone(client):
    r = _post(client, {"question": "登录失败", "index": "logs-nginx.access-default"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["index"] == "logs-nginx.access-default"
    assert body["routing"]["source"] == "given"


def test_no_queryable_index_says_so(client, monkeypatch):
    async def empty(pattern=None, include_system=False):
        return {"total": 0, "indices": []}

    monkeypatch.setattr(m, "list_indices", empty)
    r = _post(client, {"question": "随便问问"})
    assert r.status_code == 400
    assert "索引" in r.json()["detail"]


@pytest.mark.anyio
async def test_follow_up_reuses_last_turns_index(monkeypatch):
    """冷启动 2026-09-12：追问「只看第一名那个 IP」被重新路由到 nginx 错误日志 ——
    这句话本身没线索，线索在上一轮。同一会话、没手动选索引 → 沿用上一轮。"""
    from backend import main as m

    async def _no_route(*_a, **_k):
        raise AssertionError("must not call the router when the conversation already has an index")

    monkeypatch.setattr(m.index_router, "route", _no_route)
    idx, routing = await m._resolve_index("", "只看第一名那个 IP，按小时统计", [
        {"question": "top10 失败 IP", "index": "logs-linux.auth-default", "dsl": {}},
    ])
    assert idx == "logs-linux.auth-default"
    assert routing.source == "conversation"


@pytest.mark.anyio
async def test_follow_up_with_explicit_index_still_wins(monkeypatch):
    from backend import main as m

    idx, routing = await m._resolve_index("logs-nginx.*", "换个索引", [
        {"question": "q", "index": "logs-linux.auth-default", "dsl": {}},
    ])
    assert idx == "logs-nginx.*" and routing.source == "given"
