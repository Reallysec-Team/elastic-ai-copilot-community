"""LicenseGateMiddleware —— 变现闸本身的行为。

这是这次审计发现的最大测试缺口：`tests/` 下没有任何文件 import `license_gate`，
也没有任何测试碰过 `consume_unactivated_quota`。也就是说这条闸改错了，不会有
任何东西变红 —— 而它决定的是「客户付没付钱能不能用」。

这里覆盖四件事：
  1. hard-fail 状态（invalid / expired / revoked / heartbeat_lost）对生成类接口 403；
  2. 白名单路径在 hard-fail 下**仍然放行** —— 否则许可证一坏，客户连激活页
     和 license 状态都打不开，等于把人锁在自己的产品外面；
  3. 前缀白名单按「等于或是它的子路径」判，`/api/dashboards-export` 这种
     蹭前缀的新路由不会白白绕过闸；
  4. 未激活模式下额度用尽返回 402。
"""
import os
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent  # .../poc
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

os.environ.pop("RST_GATEWAY_SHARED_SECRET", None)
os.environ.pop("RST_ADMIN_TOKEN", None)

import pytest  # noqa: E402

# 导入 main 是必须的：会调 LLM 的路由是在它导入时向 llm_cost 登记的，
# 闸读的就是那份登记（见 llm_cost.py）。
from backend import license_gate, license_state as ls, llm_cost  # noqa: E402
from backend import main as _main  # noqa: E402,F401


class _Req:
    """够 dispatch 用的最小请求：它只读 `request.url.path`。

    不用 TestClient 是有意的 —— 那样每条断言都要连带把路由背后的 ES、LLM 一起
    打桩，测的东西就从「闸」漂移成「那条路由」。闸自己只看路径和 license 状态。
    """

    def __init__(self, path: str):
        self.url = type("U", (), {"path": path})()


async def _call(path: str):
    """跑一次中间件，返回 (放行了吗, 响应)。"""
    passed = []

    async def call_next(_req):
        passed.append(True)
        return "PASSED"

    resp = await license_gate.LicenseGateMiddleware(app=None).dispatch(_Req(path), call_next)
    return bool(passed), resp


def _status(monkeypatch, status: str):
    monkeypatch.setattr(ls, "get_state", lambda: {"status": status, "features": ["*"]})


# ── 1. hard-fail 状态挡住生成类接口 ───────────────────────────────────────

@pytest.mark.parametrize("status", sorted(license_gate._HARD_FAIL_STATES))
@pytest.mark.parametrize("path", sorted(llm_cost.generative()))
@pytest.mark.anyio
async def test_hard_fail_blocks_generative(monkeypatch, status, path):
    _status(monkeypatch, status)
    passed, resp = await _call(path)
    assert not passed, f"{path} 在 {status} 状态下被放行了"
    assert resp.status_code == 403


# ── 2. 许可证坏掉时，激活自救的那条路必须仍然通 ─────────────────────────

@pytest.mark.parametrize(
    "path",
    [
        "/api/license/status", "/api/license/activate", "/api/license/deactivate",
        "/api/me", "/readyz", "/healthz",
        # 登录 / 登出 / 改密码：登不进来就到不了许可页
        "/api/auth/login", "/api/auth/logout", "/api/auth/password",
    ],
)
@pytest.mark.anyio
async def test_hard_fail_still_allows_self_rescue(monkeypatch, path):
    """许可证撤销之后还能打开激活页 —— 否则客户没有任何办法把它修好。"""
    _status(monkeypatch, ls.STATUS_REVOKED)
    passed, _ = await _call(path)
    assert passed, f"{path} 在 hard-fail 下被挡住了，客户将无法自救"


# ── 3. 前缀白名单不能被蹭 ────────────────────────────────────────────────

@pytest.mark.anyio
async def test_prefix_allowlist_matches_exact_and_children(monkeypatch):
    _status(monkeypatch, ls.STATUS_REVOKED)
    for path in ("/api/dashboards", "/api/dashboards/abc", "/api/state/pref/ui"):
        passed, _ = await _call(path)
        assert passed, f"{path} 应该在白名单里"


@pytest.mark.anyio
async def test_prefix_allowlist_does_not_leak_to_sibling_paths(monkeypatch):
    """裸 startswith 的老写法会把这些路径也放过去。它们不是白名单里那条路由的
    子路径，只是名字以它开头。"""
    _status(monkeypatch, ls.STATUS_REVOKED)
    for path in ("/api/dashboards-export", "/api/admin/content-generate", "/api/statement"):
        passed, resp = await _call(path)
        assert not passed, f"{path} 蹭前缀绕过了 license 闸"
        assert resp.status_code == 403


# ── 4. 未激活额度 ────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_unactivated_quota_exhausted_returns_402(monkeypatch):
    _status(monkeypatch, ls.STATUS_UNACTIVATED)

    async def spent():
        return False

    monkeypatch.setattr(ls, "consume_unactivated_quota", spent)
    passed, resp = await _call("/api/generate")
    assert not passed
    assert resp.status_code == 402


@pytest.mark.anyio
async def test_unactivated_with_quota_left_passes(monkeypatch):
    _status(monkeypatch, ls.STATUS_UNACTIVATED)

    async def left():
        return True

    monkeypatch.setattr(ls, "consume_unactivated_quota", left)
    passed, _ = await _call("/api/generate")
    assert passed


@pytest.mark.anyio
async def test_quota_is_only_charged_on_generative_paths(monkeypatch):
    """轻量接口不该扣额度 —— 否则同步一次分诊状态就烧掉一次试用次数。"""
    _status(monkeypatch, ls.STATUS_UNACTIVATED)
    charged = []

    async def counting():
        charged.append(True)
        return True

    monkeypatch.setattr(ls, "consume_unactivated_quota", counting)
    for path in sorted(license_gate._GATED_LIGHTWEIGHT):
        await _call(path)
    assert charged == []


def test_hard_fail_403_carries_an_error_code(monkeypatch):
    """产品被锁住时那句提示必须带码 —— 否则英文界面只能原样显示中文 detail，
    而这是操作者唯一能看到的解释。"""
    from fastapi.testclient import TestClient

    from backend import api_errors, license_state as ls_mod, main

    for status, code in (
        (ls_mod.STATUS_INVALID, "license_invalid"),
        (ls_mod.STATUS_EXPIRED, "license_expired"),
        (ls_mod.STATUS_REVOKED, "license_revoked"),
        (ls_mod.STATUS_HEARTBEAT_LOST, "license_heartbeat_lost"),
    ):
        monkeypatch.setattr(
            ls_mod, "get_state", lambda s=status: {"status": s, "features": []}
        )
        r = TestClient(main.app).post(
            "/api/execute", json={"index": "logs-*", "dsl": {"query": {"match_all": {}}}}
        )
        assert r.status_code == 403, r.text
        body = r.json()
        assert body["code"] == code
        assert body["license_status"] == status
        # detail 一个字没变：审计日志和现有 curl 调用者照旧。
        assert body["detail"] == api_errors.MESSAGES[code]


@pytest.mark.anyio
async def test_unactivated_refunds_the_trial_call_when_a_sealed_feature_says_403(monkeypatch):
    """Cold-start 2026-09-12: clicking a locked paid feature (403) still burned a
    trial call. The model was never reached, so the gate gives it back."""
    from starlette.responses import JSONResponse

    from backend import license_gate, license_state as ls_mod

    monkeypatch.setattr(ls_mod, "get_state", lambda: {"status": ls_mod.STATUS_UNACTIVATED, "features": []})
    consumed, refunded = [], []

    async def consume():
        consumed.append(1)
        return True

    async def refund():
        refunded.append(1)

    monkeypatch.setattr(ls_mod, "consume_unactivated_quota", consume)
    monkeypatch.setattr(ls_mod, "refund_unactivated_quota", refund)

    async def call_next(_req):
        return JSONResponse(status_code=403, content={"code": "feature_locked"})

    mw = license_gate.LicenseGateMiddleware(app=None)
    resp = await mw.dispatch(_Req("/api/detection-rule/generate"), call_next)
    assert resp.status_code == 403
    assert len(consumed) == 1 and len(refunded) == 1
