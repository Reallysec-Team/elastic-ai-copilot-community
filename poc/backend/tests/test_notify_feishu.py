"""Feishu provider: signature, URL guard, card rendering, send classification."""
import asyncio
import base64
import hashlib
import hmac
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.notify import feishu  # noqa: E402


# ---- sign ----------------------------------------------------------------

def test_sign_matches_feishu_algorithm():
    secret, ts = "testsecret", "1699999999"
    # Independent reference: key = f"{ts}\n{secret}", empty message.
    expected = base64.b64encode(
        hmac.new(f"{ts}\n{secret}".encode(), b"", hashlib.sha256).digest()
    ).decode()
    assert feishu.sign(secret, ts) == expected


def test_sign_is_deterministic_and_secret_sensitive():
    assert feishu.sign("a", "100") == feishu.sign("a", "100")
    assert feishu.sign("a", "100") != feishu.sign("b", "100")
    assert feishu.sign("a", "100") != feishu.sign("a", "101")


# ---- validate_webhook_url (SSRF guard) -----------------------------------

def test_valid_feishu_url_passes():
    feishu.validate_webhook_url("https://open.feishu.cn/open-apis/bot/v2/hook/abc123")
    feishu.validate_webhook_url("https://open.larksuite.com/open-apis/bot/v2/hook/xyz")


@pytest.mark.parametrize("url", [
    "",
    "http://open.feishu.cn/open-apis/bot/v2/hook/abc",          # not https
    "https://evil.example.com/open-apis/bot/v2/hook/abc",       # host not allowed
    "https://open.feishu.cn/some/other/path",                   # not a bot hook
    "https://169.254.169.254/open-apis/bot/v2/hook/abc",        # SSRF metadata IP
])
def test_bad_webhook_url_rejected(url):
    with pytest.raises(ValueError):
        feishu.validate_webhook_url(url)


# ---- card rendering ------------------------------------------------------

def test_worst_severity_picks_highest():
    assert feishu._worst_severity({"low": 3, "high": 1}) == "high"
    assert feishu._worst_severity({"info": 5}) == "info"
    assert feishu._worst_severity({}) == "info"
    assert feishu._worst_severity(None) == "info"


def test_report_card_structure_and_link():
    report = {
        "period": "daily", "label": "过去 24 小时",
        "start_at": "2026-07-06T00:00", "end_at": "2026-07-07T00:00",
        "summary": {"total": 1234, "success_rate": 0.97, "unique_users": 5, "unique_indexes": 8},
        "security_triage": {"total_alerts": 40, "total_clusters": 6, "likely_fp": 2,
                            "severity_counts": {"high": 2, "low": 4}},
        "license_status": "active",
    }
    card = feishu.render_report_card(report, base_url="https://rst.example.com/")
    els = card["card"]["elements"]
    assert card["msg_type"] == "interactive"
    assert card["card"]["header"]["template"] == "orange"  # worst = high
    assert "过去 24 小时" in card["card"]["header"]["title"]["content"]
    # link button present and points at /v2/reports (no double slash)
    action = next(e for e in els if e["tag"] == "action")
    assert action["actions"][0]["url"] == "https://rst.example.com/v2/reports"
    # brand footer / RST keyword present on every card
    assert els[-1]["tag"] == "note"
    assert "RST" in els[-1]["elements"][0]["content"]
    body_md = card["card"]["elements"][0]["text"]["content"]
    assert "1,234" in body_md and "97%" in body_md


def test_report_card_without_base_url_has_no_button():
    card = feishu.render_report_card({"period": "weekly", "summary": {}})
    assert all(e["tag"] != "action" for e in card["card"]["elements"])


def test_alert_card_escapes_lark_md_injection():
    # Attacker-crafted rule content must not rewrite card layout / inject links.
    card = feishu.render_alert_card({
        "severity": "high",
        "attack_intent": "[click](http://evil.example.com)",
        "subject_field": "user.name",
        "subject_value": "*bold*`code`",
        "recommendation": "normal",
    })
    md = card["card"]["elements"][0]["text"]["content"]
    assert "[click](http://evil.example.com)" not in md  # brackets/parens escaped
    assert "\\[click\\]" in md
    assert "*bold*" not in md or "\\*bold\\*" in md


def test_alert_card_uses_severity_template():
    card = feishu.render_alert_card(
        {"severity": "critical", "rule_name": "Brute force", "subject_field": "src.ip",
         "subject_value": "10.0.0.1", "count": 12, "recommendation": "封禁来源"},
        base_url="https://rst.example.com",
    )
    assert card["card"]["header"]["template"] == "red"
    assert "Brute force" in card["card"]["header"]["title"]["content"]
    md = card["card"]["elements"][0]["text"]["content"]
    assert "CRITICAL" in md and "10.0.0.1" in md and "封禁来源" in md


# ---- send classification (retryable vs not) ------------------------------

class _FakeResp:
    def __init__(self, status_code, json_body=None, text=""):
        self.status_code = status_code
        self._json = json_body
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class _FakeClient:
    """Stand-in for httpx.AsyncClient; captures the last posted payload."""
    last_payload = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeClient.last_payload = json
        return _RESP_QUEUE.pop(0)


_RESP_QUEUE: list = []


@pytest.fixture
def fake_httpx(monkeypatch):
    _RESP_QUEUE.clear()
    _FakeClient.last_payload = None
    monkeypatch.setattr(feishu.httpx, "AsyncClient", _FakeClient)
    return _RESP_QUEUE


URL = "https://open.feishu.cn/open-apis/bot/v2/hook/abc"


def test_send_success_code_zero(fake_httpx):
    fake_httpx.append(_FakeResp(200, {"code": 0, "msg": "success"}))
    asyncio.run(feishu.send(URL, {"msg_type": "text", "content": {"text": "hi"}}))


def test_send_injects_signature_when_secret(fake_httpx):
    fake_httpx.append(_FakeResp(200, {"code": 0}))
    asyncio.run(feishu.send(URL, {"msg_type": "text"}, secret="s3cr3t", timestamp="1700000000"))
    p = _FakeClient.last_payload
    assert p["timestamp"] == "1700000000"
    assert p["sign"] == feishu.sign("s3cr3t", "1700000000")


def test_send_no_signature_without_secret(fake_httpx):
    fake_httpx.append(_FakeResp(200, {"code": 0}))
    asyncio.run(feishu.send(URL, {"msg_type": "text"}))
    assert "sign" not in _FakeClient.last_payload


def test_send_5xx_is_retryable(fake_httpx):
    fake_httpx.append(_FakeResp(503, text="upstream"))
    with pytest.raises(feishu.FeishuError) as ei:
        asyncio.run(feishu.send(URL, {}))
    assert ei.value.retryable is True


def test_send_rate_limit_code_retryable(fake_httpx):
    fake_httpx.append(_FakeResp(200, {"code": 9499, "msg": "too many request"}))
    with pytest.raises(feishu.FeishuError) as ei:
        asyncio.run(feishu.send(URL, {}))
    assert ei.value.retryable is True


def test_send_sign_mismatch_not_retryable(fake_httpx):
    fake_httpx.append(_FakeResp(200, {"code": 19024, "msg": "sign match fail"}))
    with pytest.raises(feishu.FeishuError) as ei:
        asyncio.run(feishu.send(URL, {}))
    assert ei.value.retryable is False
