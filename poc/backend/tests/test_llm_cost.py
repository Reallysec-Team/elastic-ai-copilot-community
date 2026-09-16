"""会调 LLM 的路由必须在路由那儿声明（llm_cost），额度闸和限流桶都从那里读。

这条测试盯的是那个「加一条昂贵路由、忘了同步两张枚举表」的老洞：
`/api/investigate-alert/stream`、`/api/explain-result`、`/api/reports/generate`、
`/api/kb/search` 四条曾经既不扣额度也没有桶，而这不会让任何东西变红。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))


import pytest  # noqa: E402

from backend import llm_cost, main, rate_limit  # noqa: E402

# 登记表的快照。改动这里 = 明确决定某条路由花不花钱 / 限不限流，而不是手滑。
EXPECTED_GENERATIVE = {
    "/api/generate",
    "/api/generate/stream",
    # /api/execute 故意不在这里：它只查 ES 不调模型，2026-09-12 冷启动发现每次开页面
    # 都会扣 1 次「AI 调用」额度。
    "/api/explain-log",
    "/api/explain-result",
    "/api/suggest-angles",
    "/api/investigate-alert",
    "/api/investigate-alert/stream",
    "/api/detection-rule/generate",
    "/api/triage/batch",
    "/api/report/incident",
    "/api/reports/generate",
    "/api/kb/search",
    "/api/platform/interpret",
}

# 曾经的四个漏网路由 —— 单独点名，免得快照被整体改掉时它们悄悄溜走。
PREVIOUSLY_MISSED = {
    "/api/investigate-alert/stream",
    "/api/explain-result",
    "/api/reports/generate",
    "/api/kb/search",
}


def test_generative_registry_matches_expected():
    assert set(llm_cost.generative()) == EXPECTED_GENERATIVE


@pytest.mark.parametrize("path", sorted(PREVIOUSLY_MISSED))
def test_previously_unmarked_routes_are_now_gated(path):
    assert path in llm_cost.generative()


@pytest.mark.parametrize("path", sorted(EXPECTED_GENERATIVE))
def test_every_marked_route_has_a_rate_limit_bucket(path):
    """自己有桶，或者别名到一个有桶的路径上（流式变体走这条）。"""
    rate_limit.reload()
    canonical = rate_limit._canonical_path(path)
    assert rate_limit._resolve_bucket(canonical) is not None, f"{path} 没有限流桶"


def test_registered_paths_are_real_routes():
    """登记表里不能有拼错的路径 —— 那样它保护的是一条不存在的路由。"""
    # include_router 在这个 FastAPI 版本里挂的是 `_IncludedRouter`，子路由不会
    # 摊平进 app.routes，所以要往下走一层。
    def paths(routes):
        for r in routes:
            if hasattr(r, "path"):
                yield r.path
            inner = getattr(r, "original_router", None)
            if inner is not None:
                yield from paths(inner.routes)

    declared = set(paths(main.app.routes))
    missing = sorted(p for p in llm_cost.registered() if p not in declared)
    assert not missing, f"登记了但没有这条路由: {missing}"


# 每个会真正花掉一次 LLM 调用的模块 → 把它带起来的那条（已登记的）路由。
# 上面那些测试盯的是「登记表别被手滑改坏」，盯不住「有人新写了一处 LLM 调用、
# 而它挂在一条没登记的路由上」—— `/api/alerts/ingest` 就是这么漏的：webhook 每条
# 告警一次 summarize，既不扣额度也没有桶，登记表却完全绿。
EXPECTED_LLM_CALL_SITES = {
    "agentic_investigate.py": "/api/investigate-alert",
    "alerts/summarize.py": "/api/alerts/ingest",   # + 轮询那条后台路径（无路由）
    "corrections.py": "/api/generate",             # 提问被识别为纠正时的追加调用
    "detection_rule.py": "/api/detection-rule/generate",
    "explain.py": "/api/explain-log",
    "investigate.py": "/api/investigate-alert",
    "llm.py": "/api/generate",
    "llm_router.py": "-",                          # 路由器自己，所有调用的出口
    "platform_ops/interpret.py": "/api/platform/interpret",
    "incident_report.py": "/api/report/incident",
    "suggest_angles.py": "/api/suggest-angles",
    "triage.py": "/api/triage/batch",
}


def test_every_llm_call_site_is_accounted_for():
    """新增一处 chat_completion 就必须在这里说明它挂在哪条登记过的路由上。"""
    backend = Path(__file__).resolve().parent.parent
    found = set()
    for p in sorted(backend.rglob("*.py")):
        rel = p.relative_to(backend).as_posix()
        if rel.startswith("tests/"):
            continue
        if re.search(r"chat_completion(_stream)?[(]", p.read_text(encoding="utf-8")):
            found.add(rel)
    assert found == set(EXPECTED_LLM_CALL_SITES), (
        f"新增/消失的 LLM 调用点: {sorted(found ^ set(EXPECTED_LLM_CALL_SITES))}"
    )
    registered = set(llm_cost.registered())
    for mod, route in EXPECTED_LLM_CALL_SITES.items():
        if route != "-":
            assert route in registered, f"{mod} 挂在未登记的路由 {route} 上"


def test_streaming_variants_share_their_parent_bucket():
    """改用流式接口不能绕开限流。"""
    assert rate_limit._canonical_path("/api/generate/stream") == "/api/generate"
    assert (
        rate_limit._canonical_path("/api/investigate-alert/stream")
        == "/api/investigate-alert"
    )
