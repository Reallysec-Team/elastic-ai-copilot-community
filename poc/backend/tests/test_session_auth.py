"""密码登录 / 会话 cookie 单测。

重点不是"能登录成功"，而是每一条拒绝路径都真的拒绝：过期的、改签名的、
换了密码的旧会话、以及暴力破解。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import session_auth  # noqa: E402

_NOW = 1_700_000_000.0


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("RST_ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("RST_SESSION_TTL_HOURS", raising=False)
    monkeypatch.delenv("RST_SSO_ENABLED", raising=False)
    monkeypatch.delenv("RST_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("RST_ALLOW_DEFAULT_PASSWORD", raising=False)
    session_auth._reset_throttle_for_tests()


def _enable(monkeypatch, password: str = "hunter2") -> str:
    h = session_auth.hash_password(password)
    monkeypatch.setenv("RST_ADMIN_PASSWORD_HASH", h)
    return h


# ───────────────────────────── password hashing ─────────────────────────────


def test_hash_roundtrip():
    h = session_auth.hash_password("hunter2")
    assert session_auth.verify_password("hunter2", h)
    assert not session_auth.verify_password("hunter3", h)


def test_same_password_hashes_differently():
    """随机 salt —— 两次哈希不能相同，否则 .env 泄露后可直接比对撞库。"""
    assert session_auth.hash_password("x") != session_auth.hash_password("x")


@pytest.mark.parametrize("bad", ["", "notahash", "scrypt$1$2$3", "md5$1$8$1$aa$bb", "$$$$$"])
def test_malformed_hash_rejects_rather_than_raises(bad):
    """.env 里打错一个字必须是"登不进去"，不能是 500。"""
    assert session_auth.verify_password("hunter2", bad) is False


# ───────────────────────────── credentials ─────────────────────────────


def test_credentials_need_both_halves(monkeypatch):
    _enable(monkeypatch, "hunter2")
    assert session_auth.verify_credentials("admin", "hunter2")
    assert not session_auth.verify_credentials("admin", "wrong")
    assert not session_auth.verify_credentials("root", "hunter2"), "用户名错也必须拒"


def test_username_override(monkeypatch):
    _enable(monkeypatch, "hunter2")
    monkeypatch.setenv("RST_ADMIN_USERNAME", "soc")
    assert session_auth.verify_credentials("soc", "hunter2")
    assert not session_auth.verify_credentials("admin", "hunter2")


def test_username_whitespace_tolerated(monkeypatch):
    """浏览器自动填充常带尾空格 —— 不该因此登录失败。"""
    _enable(monkeypatch, "hunter2")
    assert session_auth.verify_credentials("  admin  ", "hunter2")


# ───────────────────────────── enable / disable ─────────────────────────────


def test_ships_with_a_working_default_account():
    """开箱即用：不配任何东西也能用 admin / Admin@123 登录。"""
    assert session_auth.login_enabled() is True
    assert session_auth.using_default_password() is True
    assert session_auth.verify_credentials(
        session_auth.DEFAULT_USERNAME, session_auth.DEFAULT_PASSWORD
    )


def test_default_hash_constant_matches_default_password():
    """常量哈希是手工生成粘进去的 —— 粘错了这条就红。"""
    assert session_auth.verify_password(
        session_auth.DEFAULT_PASSWORD, session_auth.DEFAULT_PASSWORD_HASH
    )
    assert not session_auth.verify_password("Admin@1234", session_auth.DEFAULT_PASSWORD_HASH)


def test_setting_a_hash_retires_the_default(monkeypatch):
    """改过密码后，出厂口令必须立刻失效，不能两个都收。"""
    _enable(monkeypatch, "own-password")
    assert session_auth.using_default_password() is False
    assert session_auth.verify_credentials("admin", "own-password")
    assert not session_auth.verify_credentials("admin", session_auth.DEFAULT_PASSWORD)


def test_sso_wins_over_password(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("RST_SSO_ENABLED", "1")
    assert session_auth.login_enabled() is False, "两套身份系统不能同时生效"


# ───────────────────────────── session token ─────────────────────────────


def test_token_roundtrip(monkeypatch):
    _enable(monkeypatch)
    tok = session_auth.issue_token(now=_NOW)
    assert session_auth.token_valid(tok, now=_NOW + 60)


def test_expired_token_rejected(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("RST_SESSION_TTL_HOURS", "1")
    tok = session_auth.issue_token(now=_NOW)
    assert session_auth.token_valid(tok, now=_NOW + 3599)
    assert not session_auth.token_valid(tok, now=_NOW + 3601)


def test_tampered_expiry_rejected(monkeypatch):
    """把过期时间往后改必须失效 —— 签名先验，过期时间才有资格被相信。"""
    _enable(monkeypatch)
    version, sid, exp, sig = session_auth.issue_token(now=_NOW).split(".")
    forged = f"{version}.{sid}.{int(exp) + 86400}.{sig}"
    assert not session_auth.token_valid(forged, now=_NOW)


def test_tampered_session_id_rejected(monkeypatch):
    """换成别人的会话 id 也必须失效 —— 否则 v2 的身份就是可改的。"""
    _enable(monkeypatch)
    version, sid, exp, sig = session_auth.issue_token(now=_NOW).split(".")
    forged = f"{version}.{sid[:-1]}x.{exp}.{sig}"
    assert not session_auth.token_valid(forged, now=_NOW)


@pytest.mark.parametrize("junk", ["", "garbage", "v1.123", "v2.123.abc", "v1.notanint.abc"])
def test_junk_token_rejected(monkeypatch, junk):
    _enable(monkeypatch)
    assert session_auth.token_valid(junk, now=_NOW) is False


def test_password_change_invalidates_existing_sessions(monkeypatch):
    """签名密钥由密码哈希派生 —— 改密码等于踢掉所有在线会话。"""
    _enable(monkeypatch, "old-password")
    tok = session_auth.issue_token(now=_NOW)
    assert session_auth.token_valid(tok, now=_NOW + 60)

    _enable(monkeypatch, "new-password")
    assert not session_auth.token_valid(tok, now=_NOW + 60), "改密码后旧会话仍有效"


def test_ttl_invalid_falls_back_to_default(monkeypatch):
    _enable(monkeypatch)
    for bad in ("", "abc", "-5"):
        monkeypatch.setenv("RST_SESSION_TTL_HOURS", bad)
        assert session_auth.ttl_seconds() == session_auth.DEFAULT_TTL_HOURS * 3600.0


# ───────────────────────────── login throttle ─────────────────────────────


def test_throttle_trips_then_expires():
    ip = "10.0.0.5"
    for _ in range(session_auth._MAX_FAILURES):
        assert not session_auth.throttled(ip, now=_NOW)
        session_auth.record_failure(ip, now=_NOW)
    assert session_auth.throttled(ip, now=_NOW)
    # 窗口滑过去以后重新放行
    assert not session_auth.throttled(ip, now=_NOW + session_auth._FAILURE_WINDOW_S + 1)


def test_throttle_is_per_ip():
    for _ in range(session_auth._MAX_FAILURES):
        session_auth.record_failure("10.0.0.5", now=_NOW)
    assert session_auth.throttled("10.0.0.5", now=_NOW)
    assert not session_auth.throttled("10.0.0.6", now=_NOW)


def test_success_clears_failures():
    ip = "10.0.0.5"
    for _ in range(session_auth._MAX_FAILURES - 1):
        session_auth.record_failure(ip, now=_NOW)
    session_auth.clear_failures(ip)
    assert not session_auth.throttled(ip, now=_NOW)


# ───────────────────────────── request-level gate ─────────────────────────────


class _FakeRequest:
    def __init__(self, cookies: dict[str, str]):
        self.cookies = cookies


def test_session_valid_requires_login_enabled(monkeypatch):
    """SSO 接管身份时，就算带着一个签名正确的 cookie 也不算已登录。"""
    _enable(monkeypatch)
    tok = session_auth.issue_token()
    monkeypatch.setenv("RST_SSO_ENABLED", "1")
    req = _FakeRequest({session_auth.COOKIE_NAME: tok})
    assert session_auth.session_valid(req) is False


def test_session_from_default_password_dies_when_password_is_set(monkeypatch):
    """出厂口令签发的会话，在运维改完密码后必须失效。"""
    tok = session_auth.issue_token()
    assert session_auth.session_valid(_FakeRequest({session_auth.COOKIE_NAME: tok}))
    _enable(monkeypatch, "own-password")
    assert not session_auth.session_valid(_FakeRequest({session_auth.COOKIE_NAME: tok}))


def test_session_valid_reads_cookie(monkeypatch):
    _enable(monkeypatch)
    good = _FakeRequest({session_auth.COOKIE_NAME: session_auth.issue_token()})
    assert session_auth.session_valid(good)
    assert not session_auth.session_valid(_FakeRequest({}))


# ─────────────────────── 路由级：门是真的锁着的 ───────────────────────
#
# conftest 的 authenticated_operator fixture 让其余测试当作已登录，所以那道门
# 本身只剩这里在守。这几条把它还原成真实现，走完整 ASGI 栈。


@pytest.fixture
def real_gate(monkeypatch):
    """撤销 conftest 的放行，用真的 session_valid。"""
    from backend import auth as auth_mod

    monkeypatch.setattr(auth_mod, "session_valid", session_auth.session_valid)
    # TestClient 的来源是 "testclient"，不是回环地址，所以出厂口令的远程拦截
    # 会先一步拒掉这些用例。它们测的是登录门本身，不是那条策略 —— 那条由
    # test_security_hardening.py 覆盖。
    monkeypatch.setenv("RST_ALLOW_DEFAULT_PASSWORD", "1")
    from fastapi.testclient import TestClient

    from backend import main

    return TestClient(main.app)


def test_gated_route_rejects_anonymous(real_gate):
    r = real_gate.get("/api/llm/providers")
    assert r.status_code == 401
    assert r.json()["code"] == "login_required"


def test_login_endpoint_reachable_without_a_session(real_gate):
    """登录接口自己不能被登录墙挡住 —— 否则谁也进不来。"""
    r = real_gate.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401
    assert r.json()["detail"] == "账号或密码错误。"


def test_login_then_gated_route_passes(real_gate):
    ok = real_gate.post(
        "/api/auth/login",
        json={"username": "admin", "password": session_auth.DEFAULT_PASSWORD},
    )
    assert ok.status_code == 200
    assert real_gate.get("/api/llm/providers").status_code == 200


def test_admin_token_passes_without_a_session(real_gate, monkeypatch):
    """运维 curl / CI 拿不到 cookie，用 ops token 走机器通道。"""
    monkeypatch.setenv("RST_ADMIN_TOKEN", "ops-token")
    assert real_gate.get("/api/llm/providers").status_code == 401
    r = real_gate.get("/api/llm/providers", headers={"X-RST-Admin-Token": "ops-token"})
    assert r.status_code == 200


def test_wrong_admin_token_still_rejected(real_gate, monkeypatch):
    monkeypatch.setenv("RST_ADMIN_TOKEN", "ops-token")
    r = real_gate.get("/api/llm/providers", headers={"X-RST-Admin-Token": "guess"})
    assert r.status_code == 401


def test_the_throttle_table_does_not_grow_without_bound():
    """轮换源地址猜密码时，失败记录表不能只增不减。

    `_spent` 只裁剪它正好读到的那个 key，而每次换 IP 就是一个新 key ——
    挡是挡住了，内存一直涨。清掉窗口外的记录是行为中性的：那些失败本来就不算数了。
    """
    session_auth._reset_throttle_for_tests()
    t0 = 1_000_000.0
    for i in range(session_auth._MAX_TRACKED_KEYS + 200):
        session_auth.record_failure(f"10.0.{i // 256}.{i % 256}", now=t0)
    assert len(session_auth._failures) > session_auth._MAX_TRACKED_KEYS  # 都还在窗口内

    # 窗口过去之后，下一次失败会把它们清掉。
    later = t0 + session_auth._FAILURE_WINDOW_S + 1
    session_auth.record_failure("10.9.9.9", now=later)
    assert len(session_auth._failures) <= 2, session_auth._failures.keys()
    session_auth._reset_throttle_for_tests()


def test_pruning_does_not_forget_a_live_budget():
    """清理不能顺手把还在窗口内的失败记录抹掉 —— 那等于把闸门打开。"""
    session_auth._reset_throttle_for_tests()
    t0 = 2_000_000.0
    for i in range(session_auth._MAX_TRACKED_KEYS + 50):
        session_auth.record_failure(f"172.16.{i // 256}.{i % 256}", now=t0)
    for _ in range(session_auth._MAX_FAILURES):
        session_auth.record_failure("192.168.1.1", "victim", now=t0 + 1)

    assert session_auth.throttled("192.168.1.1", "victim", now=t0 + 2)
    assert session_auth.throttled("1.2.3.4", "victim", now=t0 + 2), "账号预算也还在"
    session_auth._reset_throttle_for_tests()
