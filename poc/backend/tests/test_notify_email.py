"""邮件投递：校验、渲染、以及「哪些 SMTP 错误值得重试」。

重试语义是这里最要紧的一件事。认证被拒、发件人被拒是配置错了，退避一百次还是错，
应该直接进死信让人去看；连不上、超时才值得重试。判错方向的代价是实打实的：要么
一条发不出去的信占着队列重试六轮，要么一次网络抖动把当天的报告扔进死信。
"""
import smtplib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.notify import config as cfg  # noqa: E402
from backend.notify import email as mail  # noqa: E402


# ---- 目标校验（按渠道分流） ------------------------------------------------


def test_email_target_needs_recipients():
    with pytest.raises(ValueError, match="收件人"):
        cfg._validate_target_input({"name": "运维组", "channel": "email", "recipients": []})


def test_email_target_rejects_malformed_address():
    with pytest.raises(ValueError, match="不合法"):
        cfg._validate_target_input(
            {"name": "运维组", "channel": "email", "recipients": ["not-an-address"]}
        )


def test_email_target_does_not_require_a_webhook():
    """按渠道分流的意义就在这 —— 邮件目标不该被飞书的 URL 校验拦下。"""
    cfg._validate_target_input(
        {"name": "运维组", "channel": "email", "recipients": ["soc@corp.example"]}
    )


def test_recipients_accept_a_pasted_string():
    """人是从通讯录里粘一串地址进来的，不是一个个填。"""
    assert cfg._validate_recipients("a@x.com, b@x.com;c@x.com") == [
        "a@x.com", "b@x.com", "c@x.com",
    ]


def test_recipients_dedupe():
    assert cfg._validate_recipients(["a@x.com", "a@x.com"]) == ["a@x.com"]


def test_unknown_channel_rejected():
    with pytest.raises(ValueError, match="未知渠道"):
        cfg._validate_target_input({"name": "x", "channel": "carrier-pigeon"})


# ---- SMTP 配置校验 ---------------------------------------------------------


@pytest.mark.parametrize("bad", [
    {"host": "", "port": 587, "from_addr": "a@x.com"},
    {"host": "smtp.x.com", "port": 0, "from_addr": "a@x.com"},
    {"host": "smtp.x.com", "port": 587, "from_addr": "nope"},
    {"host": "smtp.x.com", "port": 587, "from_addr": "a@x.com", "security": "rot13"},
])
def test_smtp_validation_rejects(bad):
    with pytest.raises(ValueError):
        cfg._validate_smtp(bad)


def test_smtp_validation_accepts_a_normal_config():
    cfg._validate_smtp({"host": "smtp.corp.example", "port": 465,
                        "security": "ssl", "from_addr": "copilot@corp.example"})


def test_smtp_password_never_leaves_in_the_clear():
    red = cfg._redact_smtp({"host": "smtp.x.com", "password_enc": "gAAAAA..."})
    assert "password_enc" not in red
    assert red["password_set"] is True


# ---- 渲染 -----------------------------------------------------------------


def test_report_email_carries_the_full_markdown():
    """报告全文进正文 —— 不用点链接就能读完，正是收件人选邮件的理由（IM 卡片
    有 ~30KB 上限，进不去）。"""
    body = mail.render_report_email(
        {"period": "daily", "label": "每日", "start_at": "2026-09-05T00:00:00Z",
         "end_at": "2026-09-06T00:00:00Z", "summary": {"total": 470, "success_rate": 1.0},
         "markdown": "## 概览\n调用 470 次"},
        base_url="https://copilot.corp.example",
    )
    assert "每日" in body["subject"]
    assert "调用 470 次" in body["html"]
    assert "调用 470 次" in body["text"]
    assert "copilot.corp.example" in body["html"]


def test_render_escapes_html():
    """告警标题来自检测规则，规则名是客户写的 —— 当成 HTML 拼进去就是一个注入口。"""
    body = mail.render_alert_email({"severity": "high", "title": "<script>alert(1)</script>"})
    assert "<script>" not in body["html"]
    assert "&lt;script&gt;" in body["html"]


def test_alert_subject_carries_severity():
    body = mail.render_alert_email({"severity": "critical", "title": "暴力破解后登录成功"})
    assert body["subject"].startswith("[RST][CRITICAL]")


# ---- 重试语义 --------------------------------------------------------------


async def _send_with(monkeypatch, exc):
    monkeypatch.setattr(mail.asyncio, "to_thread",
                        lambda *a, **k: (_ for _ in ()).throw(exc))

    async def fake_smtp():
        return {"host": "smtp.x.com", "port": 587, "from_addr": "a@x.com", "password": ""}

    from backend.notify import config as c
    monkeypatch.setattr(c, "get_smtp_raw", fake_smtp)
    with pytest.raises(mail.EmailError) as ei:
        await mail.send(["b@x.com"], {"subject": "s", "text": "t"})
    return ei.value


@pytest.mark.asyncio
async def test_auth_failure_is_not_retryable(monkeypatch):
    err = await _send_with(monkeypatch, smtplib.SMTPAuthenticationError(535, b"auth failed"))
    assert err.retryable is False


@pytest.mark.asyncio
async def test_connection_error_is_retryable(monkeypatch):
    err = await _send_with(monkeypatch, OSError("connection refused"))
    assert err.retryable is True


@pytest.mark.asyncio
async def test_transient_4xx_is_retryable(monkeypatch):
    err = await _send_with(monkeypatch, smtplib.SMTPResponseException(451, b"try again later"))
    assert err.retryable is True


@pytest.mark.asyncio
async def test_mailbox_unavailable_is_not_retryable(monkeypatch):
    err = await _send_with(monkeypatch, smtplib.SMTPResponseException(550, b"relay denied"))
    assert err.retryable is False


@pytest.mark.asyncio
async def test_no_smtp_configured_fails_fast(monkeypatch):
    async def empty():
        return {}

    from backend.notify import config as c
    monkeypatch.setattr(c, "get_smtp_raw", empty)
    with pytest.raises(mail.EmailError) as ei:
        await mail.send(["b@x.com"], {"subject": "s", "text": "t"})
    assert ei.value.retryable is False
