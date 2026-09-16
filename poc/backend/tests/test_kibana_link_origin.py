"""深链里的 Kibana 主机名不能由请求方说了算。

`public_kibana_url` 会拿 Origin 的 hostname 拼出 `http://<host>:5601/...`，这串
URL 要发回界面让人去点，里面还带着这次查询的 KQL。Origin 是请求方给的头 ——
`Origin: http://evil.example` 就能让网关生成一条指向别人主机的深链。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import kibana_link  # noqa: E402


class _Req:
    def __init__(self, **headers):
        self.headers = {k.lower(): v for k, v in headers.items()}


def test_same_origin_is_trusted():
    r = _Req(origin="http://gw.example:18765", host="gw.example:18765")
    assert kibana_link.trusted_origin(r) == "http://gw.example:18765"


def test_a_foreign_origin_is_ignored(caplog):
    r = _Req(origin="http://evil.example", host="gw.example:18765")
    assert kibana_link.trusted_origin(r) is None


def test_a_foreign_referer_is_ignored():
    r = _Req(referer="http://evil.example/page", host="gw.example:18765")
    assert kibana_link.trusted_origin(r) is None


def test_an_operator_named_front_end_is_trusted(monkeypatch):
    monkeypatch.setenv("RST_CORS_ORIGINS", "https://ui.corp.example")
    r = _Req(origin="https://ui.corp.example", host="gw.example:18765")
    assert kibana_link.trusted_origin(r) == "https://ui.corp.example"


def test_no_origin_at_all_is_not_an_error():
    assert kibana_link.trusted_origin(_Req(host="gw.example")) is None


def test_an_ignored_origin_falls_back_to_the_configured_kibana(monkeypatch):
    """挡住之后不是报错，是回落到 KIBANA_URL —— 深链照旧生成，只是主机名不由请求方定。"""
    monkeypatch.delenv("KIBANA_PUBLIC_URL", raising=False)
    monkeypatch.setenv("KIBANA_URL", "http://kibana:5601")
    r = _Req(origin="http://evil.example", host="gw.example:18765")
    url = kibana_link.public_kibana_url(kibana_link.trusted_origin(r))
    assert url == "http://kibana:5601"
    assert "evil.example" not in url


def test_a_trusted_origin_still_drives_the_host(monkeypatch):
    """正常浏览器那一路不能被误伤 —— 这个回落本来就是为它存在的。"""
    monkeypatch.delenv("KIBANA_PUBLIC_URL", raising=False)
    monkeypatch.setenv("KIBANA_URL", "http://kibana:5601")
    r = _Req(origin="http://10.0.0.5:18765", host="10.0.0.5:18765")
    url = kibana_link.public_kibana_url(kibana_link.trusted_origin(r))
    assert url == "http://10.0.0.5:5601"


def test_origin_ignored_is_reported_so_the_ui_can_explain(monkeypatch):
    """深链退回内部主机名这件事，界面上要说得出。

    只写进网关日志的话，运维看到的是一条打不开的链接，而原因（访问网关用的域名
    不在 RST_CORS_ORIGINS 里）在他看不见的地方。
    """
    r = _Req(origin="http://evil.example", host="gw.example:18765")
    assert kibana_link.origin_ignored(r) is True

    same = _Req(origin="http://gw.example:18765", host="gw.example:18765")
    assert kibana_link.origin_ignored(same) is False

    # 压根没带 Origin 不是「被忽略」—— 那是 curl / 后台调用，没什么要解释的。
    assert kibana_link.origin_ignored(_Req(host="gw.example")) is False
