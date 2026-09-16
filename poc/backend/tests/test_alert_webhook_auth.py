"""告警接入源 B（Kibana webhook connector）必须能在开着登录的部署上打进来。

Kibana 的 connector 只能挂静态 header，拿不到会话 cookie。登录闸对所有 /api/*
生效，于是它在端点自己那道 token 比对之前就被 401 掉了 —— 而默认部署就是开着
登录的（没开 SSO 就等于开密码登录）。客户按 .env.example 把密钥配好、connector
配好，推送全 401，产品这边没有任何痕迹，只有 Kibana 自己的日志里有个 401。

所以这条路径豁免登录闸和 SSO 强制闸，鉴权改由端点自己的常量时间比对负责。
这些用例钉的就是「豁免了，但没豁免成无鉴权入口」。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from fastapi.testclient import TestClient  # noqa: E402

from backend import auth as auth_mod, license_state, main as m, session_auth  # noqa: E402
from backend.alerts import ingest  # noqa: E402

_ALERT = {"kibana.alert.uuid": "u-1", "kibana.alert.rule.name": "r", "@timestamp": "2026-09-10T00:00:00Z"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        license_state, "get_state",
        lambda: {"status": license_state.STATUS_VALID, "features": ["*"]},
    )
    # 撤销 conftest 那条「每个请求都当作已登录」的放行 —— 这些用例测的正是
    # 没有会话的机器调用能不能进来，放行着就什么都测不到。
    monkeypatch.setattr(auth_mod, "session_valid", session_auth.session_valid)
    monkeypatch.setattr(auth_mod, "session_identity", session_auth.session_identity)
    # 密码登录打开 = 默认部署的形态（没开 SSO 就是它）。
    monkeypatch.setenv("RST_ADMIN_PASSWORD_HASH", "scrypt$16384$8$1$AAAA$BBBB")
    monkeypatch.delenv("RST_GATEWAY_SHARED_SECRET", raising=False)
    monkeypatch.delenv("RST_SSO_ENABLED", raising=False)

    async def fake_handle(alert, **kw):
        return True

    monkeypatch.setattr(ingest, "handle_new_alert", fake_handle)
    return TestClient(m.app)


def _post(client, token: str | None):
    headers = {"X-RST-Alert-Token": token} if token is not None else {}
    return client.post("/api/alerts/ingest", json={"alerts": [_ALERT]}, headers=headers)


def test_connector_gets_in_without_a_session(client, monkeypatch):
    monkeypatch.setenv("RST_ALERT_WEBHOOK_SECRET", "s3cret")
    r = _post(client, "s3cret")
    assert r.status_code == 200, r.text
    assert r.json()["ingested"] == 1


def test_wrong_token_is_the_endpoint_saying_no_not_the_login_gate(client, monkeypatch):
    monkeypatch.setenv("RST_ALERT_WEBHOOK_SECRET", "s3cret")
    r = _post(client, "wrong")
    assert r.status_code == 401
    assert r.json()["code"] == "alert_webhook_token_invalid"


def test_no_token_at_all_is_still_refused(client, monkeypatch):
    monkeypatch.setenv("RST_ALERT_WEBHOOK_SECRET", "s3cret")
    r = _post(client, None)
    assert r.status_code == 401
    assert r.json()["code"] == "alert_webhook_token_invalid"


def test_secret_unset_keeps_the_endpoint_disabled(client, monkeypatch):
    """豁免登录闸不等于开了个无鉴权入口：没配密钥时整条端点是关的。"""
    monkeypatch.delenv("RST_ALERT_WEBHOOK_SECRET", raising=False)
    r = _post(client, "anything")
    assert r.status_code == 403
    assert r.json()["code"] == "alert_webhook_disabled"


def test_shared_secret_gate_still_applies(client, monkeypatch):
    """共享密钥闸认的是「这个请求准不准发进来」，那道闸没豁免。"""
    monkeypatch.setenv("RST_ALERT_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("RST_GATEWAY_SHARED_SECRET", "gw-secret")
    assert _post(client, "s3cret").status_code == 401
    r = client.post("/api/alerts/ingest", json={"alerts": [_ALERT]},
                    headers={"X-RST-Alert-Token": "s3cret", "X-RST-Gateway-Token": "gw-secret"})
    assert r.status_code == 200, r.text
