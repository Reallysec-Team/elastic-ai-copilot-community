"""Slack incoming webhook。

  - 端点：hooks.slack.com/services/T…/B…/…（URL 本身就是凭据，见下）
  - 消息：Block Kit —— {"text": 兜底文本, "blocks": [...]}
    `text` 不是可选的：手机推送通知和无法渲染 blocks 的客户端只显示它，缺了就是
    一条「发来了一条消息」的空推送。
  - 成功判据：HTTP 200，body 是纯文本 "ok"（不是 JSON）
  - 失败：4xx + 纯文本原因（invalid_payload / channel_not_found / no_service）

没有签名。Slack 的 signing secret 是给**入站**请求验签用的，出站 webhook 只靠
URL 里那段路径 —— 所以这条 URL 泄露等于任何人都能往那个频道发消息，和企业微信
同一个性质（`wecom.py` 顶部记着同一条待办：webhook_url 应当进 secret_box）。

转义规则和另外三家都不一样：Slack 的 mrkdwn **不用反斜杠转义**，要转的是
`&`、`<`、`>` 三个 HTML 实体 —— 因为它的链接语法是 `<https://x|文字>`。对着
markdown 的习惯去转反斜杠，在 Slack 里会把反斜杠原样显示出来。
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from .errors import ChannelError
from .payload import Payload
from ..api_errors import ApiError

logger = logging.getLogger("rst.notify.slack")

ALLOWED_HOSTS = ("hooks.slack.com",)
_TIMEOUT_SECONDS = 10.0

# Slack 没有卡片配色，用 emoji 前缀带出严重度 —— 频道刷屏时靠它扫。
_SEVERITY_MARK = {
    "critical": ":red_circle:",
    "high": ":large_orange_circle:",
    "medium": ":large_yellow_circle:",
    "low": ":large_blue_circle:",
    "info": ":white_circle:",
}

# 这些原因重试没有意义：URL 作废、频道被删、body 不合法。
_PERMANENT = ("invalid_payload", "channel_not_found", "channel_is_archived",
              "no_service", "no_team", "team_disabled", "action_prohibited")


class SlackError(ChannelError):
    pass


def validate_webhook_url(url: str) -> None:
    raw = (url or "").strip()
    if not raw:
        raise ApiError("webhook_url_required")
    u = urlparse(raw)
    if u.scheme != "https":
        raise ApiError("webhook_must_be_https", channel="Slack")
    if u.hostname not in ALLOWED_HOSTS:
        raise ApiError("webhook_host_invalid", channel="Slack", host=u.hostname, expected=ALLOWED_HOSTS[0])
    if not u.path.startswith("/services/"):
        raise ApiError("slack_path_invalid")


def _esc(value: Any) -> str:
    """Slack mrkdwn 只转这三个字符。顺序要紧：`&` 必须先转，否则后面两步产生的
    `&lt;` 会被再转一次成 `&amp;lt;`。"""
    return (
        str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def render(payload: Payload) -> dict[str, Any]:
    mark = _SEVERITY_MARK.get(payload.severity, "")
    heading = f"{mark} *{_esc(payload.heading)}*"

    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": heading}},
    ]
    if payload.fields:
        # Slack 的 fields 是两列布局，一屏最多 10 个 —— 超出的部分会被整块丢掉，
        # 不是截断，所以这里自己切。
        blocks.append({
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*{_esc(label)}*\n{_esc(value)}"}
                for label, value in payload.fields[:10]
            ],
        })
    if payload.link:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"<{payload.link}|在产品中查看>"},
        })
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "RST Elastic AI Copilot"}],
    })

    # `text` 是推送通知和降级渲染看到的东西，不能省。
    return {"text": _esc(payload.heading), "blocks": blocks}


async def send(
    webhook_url: str,
    body: dict[str, Any],
    *,
    secret: str | None = None,   # Slack 出站 webhook 无签名；形参保持四渠道同形
    verify_tls: bool = True,
) -> None:
    validate_webhook_url(webhook_url)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, verify=verify_tls) as client:
            resp = await client.post(webhook_url, json=body,
                                     headers={"Content-Type": "application/json"})
    except httpx.HTTPError as e:
        raise SlackError(f"Slack 请求失败：{e}", retryable=True) from e

    if resp.status_code == 200:
        return
    # 失败时 body 是一行纯文本原因，不是 JSON —— 按 JSON 解析会把「频道被删」
    # 变成「返回的不是 JSON」，排障时看到的就是一句没用的话。
    reason = (resp.text or "").strip()[:120]
    if resp.status_code >= 500:
        raise SlackError(f"Slack HTTP {resp.status_code}: {reason}", retryable=True)
    if resp.status_code == 429:
        raise SlackError(f"Slack 限流：{reason}", retryable=True)
    raise SlackError(
        f"Slack HTTP {resp.status_code}: {reason}",
        retryable=not any(p in reason for p in _PERMANENT),
    )
