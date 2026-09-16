"""索引自动路由：名字匹配 → 模型挑 → 全部日志兜底。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend import index_router as ir


def C(name: str, docs: int = 100, profile: str | None = None) -> ir.Candidate:
    return ir.Candidate(name=name, doc_count=docs, profile=profile)


CLUSTER = [
    C("logs-nginx.access-default", 4830),
    C("logs-nginx.error-default", 600),
    C("logs-linux.auth-default", 2182),
    C("logs-mysql.slowlog-default", 420),
    C("logs-windows.system-default", 1144),
    C("metrics-system-default", 4032),
    C("kibana_sample_data_logs", 300),
]


# ── 打分是纯函数 ──────────────────────────────────────────────────────────

def test_score_ignores_tokens_every_index_shares():
    # `logs` 和 `default` 每个名字里都有，命中它们不该加分，否则所有候选同分。
    assert ir.score_candidate("logs default", "logs-nginx.access-default") == 0


def test_score_prefers_literal_over_synonym():
    literal = ir.score_candidate("nginx 5xx 有多少", "logs-nginx.access-default")
    synonym = ir.score_candidate("网站 5xx 有多少", "logs-nginx.access-default")
    assert literal > synonym > 0


# ── 第 1 步：名字匹配 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chinese_question_routes_by_synonym():
    r = await ir.route("最近 24 小时登录失败最多的账号", CLUSTER)
    assert r.index == "logs-linux.auth-default"
    assert r.source == "name"


@pytest.mark.asyncio
async def test_slowlog_question_routes_by_synonym():
    r = await ir.route("最慢的 10 条慢查询", CLUSTER)
    assert r.index == "logs-mysql.slowlog-default"


@pytest.mark.asyncio
async def test_single_candidate_short_circuits():
    r = await ir.route("随便问点什么", [C("only-index")])
    assert r.index == "only-index"


# ── 第 2 步：模型挑 ───────────────────────────────────────────────────────

def _chat_returning(payload: dict):
    async def chat(**_kwargs):
        content = json.dumps(payload, ensure_ascii=False)
        msg = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)]), "fake"
    return chat


@pytest.mark.asyncio
async def test_model_picks_when_name_is_ambiguous():
    # 「nginx」同时命中 access 和 error 两个索引，名字分不出来 → 交给模型。
    chat = _chat_returning({"indices": ["logs-nginx.error-default"], "reason": "问的是报错"})
    r = await ir.route("nginx 最近报错多不多", CLUSTER, chat=chat)
    assert r.index == "logs-nginx.error-default"
    assert r.source == "model"
    assert r.reason == "问的是报错"


@pytest.mark.asyncio
async def test_model_reply_is_filtered_against_the_candidate_list():
    # 模型回一个不存在的索引名，绝不能直接打给 ES。
    chat = _chat_returning({"indices": [".security-7", "logs-nginx.error-default"]})
    r = await ir.route("nginx 出什么问题了", CLUSTER, chat=chat)
    assert r.index == "logs-nginx.error-default"


@pytest.mark.asyncio
async def test_model_failure_falls_back_to_scope():
    async def chat(**_kwargs):
        raise RuntimeError("provider down")

    r = await ir.route("这个问题谁也看不懂", CLUSTER, chat=chat)
    assert r.source == "scope"
    assert "," in r.index


# ── 第 3 步：兜底 ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scope_is_ordered_by_doc_count_and_capped():
    many = [C(f"idx-{i}", docs=i) for i in range(1, 21)]
    r = await ir.route("无法判断的问题", many)
    names = r.index.split(",")
    assert len(names) == ir.SCOPE_LIMIT
    assert names[0] == "idx-20"  # 文档最多的排前面


@pytest.mark.asyncio
async def test_empty_indices_are_left_out_of_the_scope():
    r = await ir.route("无法判断的问题", [C("has-data", 10), C("empty", 0)])
    assert r.index == "has-data"


@pytest.mark.asyncio
async def test_no_candidates_returns_empty_instead_of_guessing():
    r = await ir.route("任何问题", [])
    assert r.index == ""
    assert r.considered == []


@pytest.mark.asyncio
async def test_profiles_hook_failure_does_not_break_routing():
    async def profiles(_candidates):
        raise RuntimeError("mapping fetch failed")

    chat = _chat_returning({"indices": ["logs-nginx.error-default"]})
    r = await ir.route("nginx 怎么了", CLUSTER, chat=chat, profiles=profiles)
    assert r.index == "logs-nginx.error-default"
