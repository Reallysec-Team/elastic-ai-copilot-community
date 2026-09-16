"""Feishu (Lark) custom-bot webhook provider.

Pure helpers (``sign``, ``render_report_card``, ``render_alert_card``,
``validate_webhook_url``) + one thin async ``send``. Kept provider-agnostic at
the outbox layer so Slack/DingTalk/email can slot in later, but Feishu is the
only implementation today.

Feishu custom bot reference:
  - endpoint host: open.feishu.cn (CN) / open.larksuite.com (intl)
  - text:        {"msg_type":"text","content":{"text": "..."}}
  - card:        {"msg_type":"interactive","card": {...}}
  - signature (when the bot enables 签名校验):
        string_to_sign = f"{timestamp}\n{secret}"
        sign = base64( HMAC_SHA256(key=string_to_sign, msg=b"") )
    and {"timestamp": ts, "sign": sign} are merged into the POST body.
  - success is code==0 in the JSON body (HTTP is often 200 even on error).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from .errors import ChannelError
from .payload import Payload, from_alert, from_report, worst_severity
from ..api_errors import ApiError

logger = logging.getLogger("rst.notify.feishu")

# Only these hosts may receive a webhook POST (SSRF guard — the URL is
# operator-configured but still crosses a trust boundary).
ALLOWED_HOSTS = ("open.feishu.cn", "open.larksuite.com")

_SEVERITY_TEMPLATE = {
    "critical": "red",
    "high": "orange",
    "medium": "yellow",
    "low": "green",
    "info": "grey",
}
_TIMEOUT_SECONDS = 8.0


class FeishuError(ChannelError):
    """Raised by ``send`` on a non-retryable or exhausted-retry failure. Carries
    ``retryable`` so the outbox can decide whether to back off or dead-letter."""

    def __init__(self, message: str, *, retryable: bool):
        super().__init__(message, retryable=retryable)


def validate_webhook_url(url: str) -> None:
    """Raise ValueError unless ``url`` is an https Feishu/Lark bot webhook.

    Enforced at every trust boundary: config write AND send-time (defence in
    depth — a target smuggled past config validation still can't POST elsewhere).
    """
    if not url or not isinstance(url, str):
        raise ApiError("webhook_url_required")
    parsed = urlparse(url.strip())
    if parsed.scheme != "https":
        raise ApiError("feishu_url_must_be_https")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise ApiError(
            # 空主机用一个不带语言的记号：它会原样进 params，英文界面下不该冒出中文。
            "feishu_host_not_allowed", host=host or '—', allowed=', '.join(ALLOWED_HOSTS)
        )
    if "/open-apis/bot/v2/hook/" not in parsed.path:
        raise ApiError("feishu_path_invalid")


def sign(secret: str, timestamp: str) -> str:
    """Feishu bot signature: base64(HMAC-SHA256(key=f'{ts}\\n{secret}', msg=b'')).

    Pure + deterministic given (secret, timestamp) so it's unit-testable against
    Feishu's documented vector.
    """
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _worst_severity(counts: dict[str, int] | None) -> str:
    """搬到了 payload.worst_severity（渠道无关）。这里留个转发，既有调用和测试
    不必跟着改。"""
    return worst_severity(counts)


# Brand footer note on every card. Doubles as the "RST" keyword that a Feishu bot
# with 关键词 security enabled requires the message to contain.
_FOOTER = {"tag": "note", "elements": [{"tag": "plain_text", "content": "RST Elastic AI Copilot"}]}


def _card(header_title: str, template: str, elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap card elements into a full interactive-message body."""
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": template,
                "title": {"tag": "plain_text", "content": header_title},
            },
            "elements": [*elements, _FOOTER],
        },
    }


_LARK_MD_META = "\\`*_[]()~"


def _esc(value: Any) -> str:
    """Escape Lark-markdown metacharacters in attacker-influenced values (alert
    rule names, subjects, etc.) so crafted content can't rewrite card layout or
    inject links into the official alert channel."""
    s = str(value)
    for ch in _LARK_MD_META:
        s = s.replace(ch, "\\" + ch)
    return s


def _md(content: str) -> dict[str, Any]:
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}


def _action_button(text: str, url: str) -> dict[str, Any]:
    return {
        "tag": "action",
        "actions": [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": text},
                "type": "primary",
                "url": url,
            }
        ],
    }


def render(payload: Payload, *, base_url: str = "") -> dict[str, Any]:
    """把中立事件渲染成飞书卡片。

    值一律转义：值里带攻击者可控内容（规则名、主体、建议）的场合，未转义的
    lark_md 元字符可以在官方告警通道里改写卡片版式、塞进一个链接。对数字和时间
    转义是无害的，所以不区分 —— 少一条「这个字段要不要转」的判断题，就少一个
    以后新增字段时忘掉的地方。
    """
    template = _SEVERITY_TEMPLATE.get(payload.severity, "blue")
    lines = [f"**{_esc(label)}**：{_esc(value)}" for label, value in payload.fields]
    elements: list[dict[str, Any]] = [_md("\n".join(lines))]
    if payload.link:
        elements.append(_action_button(
            "查看完整报告" if payload.kind == "report" else "在产品中查看", payload.link,
        ))
    return _card(payload.heading, template, elements)


def render_report_card(report: dict[str, Any], *, base_url: str = "") -> dict[str, Any]:
    """Render a scheduled 巡检报告 as a Feishu card (summary + link, never the
    full markdown — cards cap ~30KB and the full report lives in the app)."""
    return render(from_report(report, base_url=base_url))


def render_alert_card(alert: dict[str, Any], *, base_url: str = "") -> dict[str, Any]:
    """Render one real-time alert (or triage cluster) as a Feishu card."""
    return render(from_alert(alert, base_url=base_url))


def render_report_link_card(
    title: str, severity: str, doc_url: str | None, *, base_url: str = ""
) -> dict[str, Any]:
    """Group card for a forwarded investigation REPORT: a short header + a button
    that opens the full report. The card body is only a teaser (cards truncate
    long text), so the full report lives in the linked Feishu doc — the button is
    the point. Falls back to the in-product link when no doc was created."""
    sev = (severity or "info").lower()
    template = _SEVERITY_TEMPLATE.get(sev, "blue")
    lines = [
        f"**严重度**：{sev.upper()}",
        "已生成完整调查报告。卡片仅为提要，点击下方打开全文。",
    ]
    elements: list[dict[str, Any]] = [_md("\n".join(lines))]
    if doc_url:
        elements.append(_action_button("打开完整报告（飞书文档）", doc_url))
    elif base_url:
        elements.append(_action_button("在产品中查看", f"{base_url.rstrip('/')}/v2/triage"))
    return _card(f"调查报告 · {_esc(title)}", template, elements)


async def send(
    webhook_url: str,
    body: dict[str, Any],
    *,
    secret: str | None = None,
    verify_tls: bool = True,
    timestamp: str | None = None,
) -> None:
    """POST a rendered card to a Feishu bot webhook. Raises ``FeishuError`` on
    failure with ``retryable`` set. Never raises anything else.

    ``timestamp`` is injectable for tests; production stamps ``int(time.time())``.
    """
    validate_webhook_url(webhook_url)  # boundary re-check
    payload = dict(body)
    if secret:
        ts = timestamp or str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = sign(secret, ts)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, verify=verify_tls) as client:
            resp = await client.post(
                webhook_url, json=payload, headers={"Content-Type": "application/json"}
            )
    except httpx.HTTPError as e:
        # Network/timeout — transient, worth a retry.
        raise FeishuError(f"飞书请求失败：{e}", retryable=True) from e

    if resp.status_code >= 500:
        raise FeishuError(f"飞书 HTTP {resp.status_code}", retryable=True)
    if resp.status_code >= 400:
        # 4xx (bad URL/payload/rate) — mostly non-retryable except 429.
        raise FeishuError(
            f"飞书 HTTP {resp.status_code}: {resp.text[:200]}",
            retryable=resp.status_code == 429,
        )

    # HTTP 200 but Feishu signals logical errors in the JSON body.
    try:
        data = resp.json()
    except ValueError:
        return  # non-JSON 2xx — treat as delivered
    code = data.get("code")
    if code not in (0, None):
        # 9499 = rate limited; 19024 = sign mismatch (config error, non-retryable).
        retryable = code in (9499,)
        raise FeishuError(f"飞书 code={code} msg={data.get('msg')}", retryable=retryable)
