"""SMTP 邮件投递。

报告和告警走的是同一个 outbox（幂等入队、指数退避、租约、死信），这里只负责
「把一封信发出去」和「这封信长什么样」。

为什么邮件单独一档而不是又一个 webhook：报告是要留档、要转发、要发给不在 IM 群里
的人（合规、审计、领导）的东西，IM 卡片给不了这些。告警才是 IM 的主场。

正文用 HTML + 纯文本双份（``multipart/alternative``）。附件先不做 —— PDF 要往镜像
里塞一整套排版引擎和中文字体，几十上百 MB，等客户真提再说；Markdown 原文已经在
HTML 正文里了。

重试语义跟飞书那边对齐：``EmailError.retryable`` 决定 outbox 是退避重试还是直接
进死信。认证失败、地址被拒是配置错了，重试一百次也是错；连不上、超时、4xx 限流
才值得重试。
"""

from __future__ import annotations

import asyncio
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from typing import Any

from .errors import ChannelError
from .payload import Payload, from_alert, from_report

logger = logging.getLogger("rst.notify.email")

_TIMEOUT_S = 20.0


class EmailError(ChannelError):
    pass


# ---- 渲染 ---------------------------------------------------------------

_SEVERITY_COLOR = {
    "critical": "#b42318",
    "high": "#c4320a",
    "medium": "#b54708",
    "low": "#175cd3",
    "info": "#475467",
}


def _esc(v: Any) -> str:
    return (
        str(v if v is not None else "—")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _shell(title: str, accent: str, rows: list[tuple[str, Any]], body_md: str = "",
           link: str = "") -> tuple[str, str]:
    """→ (html, text)。内联样式而不是 <style>：邮件客户端对样式表的支持差得离谱，
    Outlook 会整块丢掉。"""
    tr = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;color:#667085;'
        f'white-space:nowrap;vertical-align:top">{_esc(k)}</td>'
        f'<td style="padding:6px 0;color:#101828">{_esc(v)}</td></tr>'
        for k, v in rows
    )
    body_html = ""
    if body_md:
        # 报告正文是 Markdown。这里不引 Markdown 渲染器（又一个依赖，且邮件里
        # 富排版会被各家客户端改得面目全非）—— 等宽预格式化，原文照实呈现。
        body_html = (
            '<pre style="margin:16px 0 0;padding:12px;background:#f9fafb;'
            'border:1px solid #eaecf0;border-radius:8px;white-space:pre-wrap;'
            'word-break:break-word;font:12px/1.6 ui-monospace,Menlo,Consolas,monospace;'
            f'color:#344054">{_esc(body_md)}</pre>'
        )
    link_html = (
        f'<p style="margin:16px 0 0"><a href="{_esc(link)}" '
        f'style="color:#175cd3">在控制台中查看</a></p>' if link else ""
    )
    html = (
        '<div style="font:14px/1.6 -apple-system,BlinkMacSystemFont,\'Segoe UI\','
        'Roboto,\'Helvetica Neue\',Arial,sans-serif;color:#101828;max-width:680px">'
        f'<div style="border-left:3px solid {accent};padding-left:12px;margin-bottom:16px">'
        f'<div style="font-size:16px;font-weight:600">{_esc(title)}</div></div>'
        f'<table cellpadding="0" cellspacing="0" role="presentation">{tr}</table>'
        f'{body_html}{link_html}'
        '<p style="margin:24px 0 0;color:#98a2b3;font-size:12px">'
        'RST Elastic AI Copilot 自动发送</p></div>'
    )
    text_rows = "\n".join(f"{k}: {v if v is not None else '—'}" for k, v in rows)
    text = f"{title}\n\n{text_rows}"
    if body_md:
        text += f"\n\n{body_md}"
    if link:
        text += f"\n\n在控制台中查看：{link}"
    return html, text


def render(payload: Payload) -> dict[str, Any]:
    """把中立事件渲染成一封信。

    报告全文进正文：邮件没有 IM 卡片那个 ~30KB 上限，而「不用点链接就能读完」正是
    收件人选择邮件的理由。
    """
    accent = _SEVERITY_COLOR.get(payload.severity, "#175cd3")
    html, text = _shell(payload.heading, accent, list(payload.fields),
                        body_md=payload.body_md[:200_000], link=payload.link)
    if payload.kind == "report":
        subject = f"[RST] {payload.subject}巡检报告 · {str(payload.extra.get('end_at') or '')[:10]}"
    else:
        subject = f"[RST][{payload.severity.upper()}] {payload.subject}"
    return {"subject": subject, "html": html, "text": text}


def render_report_email(report: dict[str, Any], *, base_url: str = "") -> dict[str, Any]:
    return render(from_report(report, base_url=base_url))


def render_alert_email(alert: dict[str, Any], *, base_url: str = "") -> dict[str, Any]:
    return render(from_alert(alert, base_url=base_url))


# ---- 发送 ---------------------------------------------------------------

# 认证被拒、发件人/收件人被拒 —— 配置错了，退避一百次也还是错，直接进死信。
_PERMANENT_CODES = {535, 530, 550, 553, 554}
_PERMANENT_HINT = re.compile(r"auth|denied|not allowed|relay", re.I)


def _send_blocking(smtp: dict[str, Any], recipients: list[str], body: dict[str, Any]) -> None:
    msg = EmailMessage()
    msg["Subject"] = body.get("subject") or "RST Elastic AI Copilot"
    from_addr = smtp["from_addr"]
    msg["From"] = formataddr((smtp.get("from_name") or "RST Elastic AI Copilot", from_addr))
    # 收件人放 To 而不是 Bcc：这是内部投递，谁收到了对彼此不是秘密，而 Bcc 常被
    # 反垃圾规则减分。
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body.get("text") or "")
    if body.get("html"):
        msg.add_alternative(body["html"], subtype="html")

    security = (smtp.get("security") or "starttls").lower()
    host, port = smtp["host"], int(smtp["port"])
    ctx = ssl.create_default_context()
    if security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=_TIMEOUT_S, context=ctx)
    else:
        server = smtplib.SMTP(host, port, timeout=_TIMEOUT_S)
    try:
        if security == "starttls":
            server.starttls(context=ctx)
        if smtp.get("username"):
            server.login(smtp["username"], smtp.get("password") or "")
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001 — 关闭失败不影响已经发出去的信
            pass


async def send(recipients: list[str], body: dict[str, Any]) -> None:
    """把一封信发出去。smtplib 是阻塞的，丢进线程池 —— 不能让一次 SMTP 握手把
    整个网关的事件循环卡住。"""
    from . import config as notify_config

    if not recipients:
        raise EmailError("没有收件人", retryable=False)
    smtp = await notify_config.get_smtp_raw()
    if not (smtp.get("host") and smtp.get("from_addr")):
        raise EmailError("尚未配置 SMTP 服务器，无法发信", retryable=False)
    try:
        await asyncio.to_thread(_send_blocking, smtp, recipients, body)
    except smtplib.SMTPResponseException as e:
        permanent = e.smtp_code in _PERMANENT_CODES or bool(
            _PERMANENT_HINT.search(str(e.smtp_error or ""))
        )
        raise EmailError(f"SMTP {e.smtp_code}: {e.smtp_error!r}", retryable=not permanent)
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused,
            smtplib.SMTPSenderRefused) as e:
        raise EmailError(f"SMTP 拒绝：{e}", retryable=False)
    except (OSError, smtplib.SMTPException) as e:
        # 连不上 / 超时 / 协议中断 —— 值得重试。
        raise EmailError(f"SMTP 发送失败：{e}", retryable=True)
