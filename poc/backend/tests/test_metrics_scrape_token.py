"""/metrics 的可选抓取令牌。

它不在 /api/* 下面，所以共享密钥闸和登录闸都不管 —— 在不挂 Caddy 的局域网部署上，
谁能连到端口谁就能读路由使用量和 license 状态。配了 RST_METRICS_TOKEN 就要求带上；
不配维持原状，免得升级之后 Prometheus 突然抓不到。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from fastapi.testclient import TestClient  # noqa: E402

from backend import main  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("RST_METRICS_TOKEN", raising=False)
    monkeypatch.delenv("RST_ADMIN_TOKEN", raising=False)
    return TestClient(main.app)


def test_unset_token_keeps_the_endpoint_open(client):
    """既有部署的 Prometheus 配置不用改。"""
    assert client.get("/metrics").status_code == 200


def test_a_configured_token_is_required(client, monkeypatch):
    monkeypatch.setenv("RST_METRICS_TOKEN", "scrape-me")
    r = client.get("/metrics")
    assert r.status_code == 401
    assert r.json()["code"] == "metrics_token_required"


def test_the_header_form_is_accepted(client, monkeypatch):
    monkeypatch.setenv("RST_METRICS_TOKEN", "scrape-me")
    r = client.get("/metrics", headers={"X-RST-Metrics-Token": "scrape-me"})
    assert r.status_code == 200


def test_the_bearer_form_is_accepted(client, monkeypatch):
    """Prometheus 的 scrape config 里 bearer_token 是最省事的写法。"""
    monkeypatch.setenv("RST_METRICS_TOKEN", "scrape-me")
    r = client.get("/metrics", headers={"Authorization": "Bearer scrape-me"})
    assert r.status_code == 200


def test_a_wrong_token_is_refused(client, monkeypatch):
    monkeypatch.setenv("RST_METRICS_TOKEN", "scrape-me")
    r = client.get("/metrics", headers={"X-RST-Metrics-Token": "nope"})
    assert r.status_code == 401


def test_the_ops_token_also_gets_in(client, monkeypatch):
    """运维手上本来就有 RST_ADMIN_TOKEN，不必再发一个。"""
    monkeypatch.setenv("RST_METRICS_TOKEN", "scrape-me")
    monkeypatch.setenv("RST_ADMIN_TOKEN", "ops-token")
    r = client.get("/metrics", headers={"X-RST-Admin-Token": "ops-token"})
    assert r.status_code == 200


def test_the_401_says_how_to_authenticate(client, monkeypatch):
    """抓取端是机器：401 得带 WWW-Authenticate，否则它只知道被拒了。"""
    monkeypatch.setenv("RST_METRICS_TOKEN", "scrape-me")
    r = client.get("/metrics")
    assert r.status_code == 401
    assert r.headers.get("WWW-Authenticate", "").lower().startswith("bearer")
