"""阶段 01 安全加固：四条都写成"应当被拒绝"的用例。

这里每一条对应 auth 现状测量里的一个编号问题（S1/S2/S4），断言的都是
拒绝路径。正向路径同样要有，但只是为了证明这些拒绝没有把正常使用一起
拦掉 —— 一条把所有人都挡在外面的防护，等于把可用性当安全用。
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
    for var in (
        "RST_ADMIN_PASSWORD_HASH",
        "RST_ADMIN_USERNAME",
        "RST_ALLOW_DEFAULT_PASSWORD",
        "RST_CORS_ORIGINS",
        "RST_SSO_ENABLED",
        "RST_ADMIN_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
    session_auth._reset_throttle_for_tests()


@pytest.fixture
def client(monkeypatch):
    """完整 ASGI 栈，且撤销 conftest 对 session_valid 的放行。"""
    from fastapi.testclient import TestClient

    from backend import auth as auth_mod
    from backend import main

    monkeypatch.setattr(auth_mod, "session_valid", session_auth.session_valid)
    return TestClient(main.app)


def _login(client) -> None:
    """拿一个真会话 —— 用来证明 CSRF 拒绝发生在"已登录"之后，而不是被登录墙顺手挡掉。"""
    r = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": session_auth.DEFAULT_PASSWORD},
    )
    assert r.status_code == 200, r.text


# ─────────────────────── S1 · 跨站请求（CSRF 纵深防御） ───────────────────────


def test_cross_site_post_to_admin_endpoint_is_rejected(client, monkeypatch):
    """诱导已登录操作员访问恶意页面 → 那个页面 POST 到管理端点，必须被拒。

    这是 S1 的原始威胁场景：`is_admin()` 在密码登录下只要有 session 就为真，
    所以 23 个 require_admin 端点全是 cookie 可达的状态变更。
    """
    monkeypatch.setenv("RST_ALLOW_DEFAULT_PASSWORD", "1")
    _login(client)
    r = client.post(
        "/api/settings",
        json={},
        headers={"Origin": "http://evil.example.com"},
    )
    assert r.status_code == 403
    assert "跨站" in r.json()["detail"]


@pytest.mark.parametrize(
    "method,path",
    [
        ("put", "/api/state/prefs/x"),
        ("delete", "/api/state/prefs/x"),
        ("post", "/api/llm/providers/save"),
    ],
)
def test_every_state_changing_method_is_covered(client, method, path):
    """不只 POST —— PUT/DELETE 同样是状态变更，漏一个就是一个缺口。"""
    r = getattr(client, method)(path, headers={"Origin": "http://evil.example.com"})
    assert r.status_code == 403


def test_sandboxed_origin_null_is_not_treated_as_absent(client):
    """`Origin: null`（sandbox iframe / data: URL）不是"没有 Origin"，不能放行。"""
    r = client.post("/api/settings", json={}, headers={"Origin": "null"})
    assert r.status_code == 403


def test_same_origin_post_passes(client, monkeypatch):
    monkeypatch.setenv("RST_ALLOW_DEFAULT_PASSWORD", "1")
    _login(client)
    r = client.post(
        "/api/settings",
        json={},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code != 403


def test_origin_matches_on_host_not_scheme(client, monkeypatch):
    """TLS 在 Caddy 终止，网关看到的是 http —— 比对 scheme 会拒掉每一个真实请求。"""
    monkeypatch.setenv("RST_ALLOW_DEFAULT_PASSWORD", "1")
    _login(client)
    r = client.post(
        "/api/settings",
        json={},
        headers={"Origin": "https://testserver"},
    )
    assert r.status_code != 403


def test_operator_named_origin_is_allowed(client, monkeypatch):
    monkeypatch.setenv("RST_CORS_ORIGINS", "https://soc.corp.example")
    monkeypatch.setenv("RST_ALLOW_DEFAULT_PASSWORD", "1")
    _login(client)
    r = client.post(
        "/api/settings",
        json={},
        headers={"Origin": "https://soc.corp.example"},
    )
    assert r.status_code != 403


def test_no_origin_still_passes(client, monkeypatch):
    """curl / CI / admin-token 机器通道不带 Origin，也不带可被利用的环境 cookie。

    拒绝它们，是为了防一个浏览器才会发起的攻击而打断所有自动化。
    """
    monkeypatch.setenv("RST_ADMIN_TOKEN", "ops-token")
    r = client.get("/api/llm/providers", headers={"X-RST-Admin-Token": "ops-token"})
    assert r.status_code == 200


def test_safe_methods_are_not_gated(client, monkeypatch):
    monkeypatch.setenv("RST_ADMIN_TOKEN", "ops-token")
    r = client.get(
        "/api/llm/providers",
        headers={"X-RST-Admin-Token": "ops-token", "Origin": "http://evil.example.com"},
    )
    assert r.status_code == 200


# ─────────────────────── S2 · 出厂口令 / Secure cookie ───────────────────────


def test_default_password_refuses_remote_login(client):
    """出厂口令 + 非回环来源 = 拒绝。启动 WARNING 从来没人看。"""
    r = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": session_auth.DEFAULT_PASSWORD},
    )
    assert r.status_code == 403
    assert "出厂密码" in r.json()["detail"]


def test_default_password_refusal_does_not_depend_on_the_password_being_right(client):
    """密码错也返回同一个 403 —— 否则这条拒绝本身就成了口令预言机。"""
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 403


def test_loopback_can_still_use_the_default_password():
    """运维站在机器前的第一次登录必须还能进，否则等于把自己锁在外面。"""
    assert not session_auth.default_password_blocks("127.0.0.1")
    assert not session_auth.default_password_blocks("::1")


def test_remote_is_blocked_and_unknown_source_fails_closed():
    assert session_auth.default_password_blocks("10.0.0.5")
    assert session_auth.default_password_blocks("unknown")
    assert session_auth.default_password_blocks("")


def test_setting_a_hash_lifts_the_block(monkeypatch):
    monkeypatch.setenv("RST_ADMIN_PASSWORD_HASH", session_auth.hash_password("hunter2"))
    assert not session_auth.default_password_blocks("10.0.0.5")


def test_escape_hatch_lifts_the_block(monkeypatch):
    monkeypatch.setenv("RST_ALLOW_DEFAULT_PASSWORD", "1")
    assert not session_auth.default_password_blocks("10.0.0.5")


def test_secure_cookie_set_behind_a_tls_terminating_proxy():
    """S2 的另一半：Caddy 终止 TLS 后 request.url.scheme 恒为 http，
    所以 `Secure` 在真实 HTTPS 部署上从来没被设上过。"""
    from starlette.requests import Request
    from starlette.responses import Response

    def _req(headers: dict[str, str], scheme: str = "http") -> Request:
        return Request(
            {
                "type": "http",
                "scheme": scheme,
                "path": "/",
                "server": ("gateway", 8000),
                "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            }
        )

    assert session_auth.request_is_https(_req({"x-forwarded-proto": "https"}))
    # 多跳时取最左 —— 那一跳才是面对浏览器的。
    assert session_auth.request_is_https(_req({"x-forwarded-proto": "https, http"}))
    assert not session_auth.request_is_https(_req({"x-forwarded-proto": "http"}))
    assert not session_auth.request_is_https(_req({}))
    assert session_auth.request_is_https(_req({}, scheme="https"))

    resp = Response()
    session_auth.set_session_cookie(resp, _req({"x-forwarded-proto": "https"}))
    assert "Secure" in resp.headers["set-cookie"]

    plain = Response()
    session_auth.set_session_cookie(plain, _req({}))
    assert "Secure" not in plain.headers["set-cookie"]


# ─────────────────────────── S4 · 登录限速 ───────────────────────────


def test_same_account_is_locked_even_from_rotating_ips():
    """S4 的核心：按 IP 计数时，换地址就能对同一个账号无限猜下去。"""
    for i in range(session_auth._MAX_FAILURES):
        ip = f"10.0.0.{i}"
        assert not session_auth.throttled(ip, "admin", now=_NOW)
        session_auth.record_failure(ip, "admin", now=_NOW)
    assert session_auth.throttled("10.9.9.9", "admin", now=_NOW)


def test_locking_one_account_does_not_lock_another():
    for i in range(session_auth._MAX_FAILURES):
        session_auth.record_failure(f"10.0.0.{i}", "admin", now=_NOW)
    assert not session_auth.throttled("10.9.9.9", "someone-else", now=_NOW)


def test_account_lock_expires_with_the_window():
    for i in range(session_auth._MAX_FAILURES):
        session_auth.record_failure(f"10.0.0.{i}", "admin", now=_NOW)
    assert session_auth.throttled("10.9.9.9", "admin", now=_NOW)
    assert not session_auth.throttled(
        "10.9.9.9", "admin", now=_NOW + session_auth._FAILURE_WINDOW_S + 1
    )


def test_account_name_is_namespaced_against_the_ip_budget():
    """账号叫 "10.0.0.1" 时不能和那个 IP 共用一份预算。"""
    for _ in range(session_auth._MAX_FAILURES):
        session_auth.record_failure("10.0.0.1", "", now=_NOW)
    assert session_auth.throttled("10.0.0.1", "", now=_NOW)
    assert not session_auth.throttled("172.16.0.1", "10.0.0.1", now=_NOW)


def test_success_clears_both_budgets():
    session_auth.record_failure("10.0.0.1", "admin", now=_NOW)
    session_auth.clear_failures("10.0.0.1", "admin")
    assert not session_auth.throttled("10.0.0.1", "admin", now=_NOW)
    assert session_auth._failures.get("user:admin") in (None, [])


def test_account_matching_ignores_case_and_padding():
    for i in range(session_auth._MAX_FAILURES):
        session_auth.record_failure(f"10.0.0.{i}", "Admin", now=_NOW)
    assert session_auth.throttled("10.9.9.9", "  admin  ", now=_NOW)
