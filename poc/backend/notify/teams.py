"""Microsoft Teams incoming webhook。

**两代端点都要认**，这是接 Teams 时最容易踩的一脚：

  - 旧：Office 365 connector —— {tenant}.webhook.office.com / outlook.office.com。
    微软已宣布停用，但客户环境里存量还在，不能只认新的。
  - 新：Power Automate「Workflows」—— *.logic.azure.com（含
    prod-XX.westus.logic.azure.com 这类区域前缀）。新建的 Teams webhook 都是这个。

消息体用 **Adaptive Card 装在 message 信封里**，两代端点都认：

    {"type":"message","attachments":[{"contentType":
      "application/vnd.microsoft.card.adaptive","content":{…}}]}

旧连接器自己的 MessageCard（`@type: MessageCard`）只有旧端点认，写它等于把新客户
挡在门外。

成功判据：**2xx 即成功，body 不可依赖** —— 旧连接器返回 200 + 纯文本 "1"，
Workflows 返回 202 + 空 body。按 JSON 解析或者要求 body 里有什么，两边必炸一边。

没有签名：URL 本身就是凭据（与 Slack、企业微信同一性质，见 wecom.py 顶部那条
关于 webhook_url 应当加密存储的待办）。
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from .errors import ChannelError
from .payload import Payload
from ..api_errors import ApiError

logger = logging.getLogger("rst.notify.teams")

# 后缀匹配而不是全等：Workflows 的主机名带区域和租户前缀
# （prod-27.southeastasia.logic.azure.com、{tenant}.webhook.office.com）。
ALLOWED_HOST_SUFFIXES = (
    ".webhook.office.com",
    "outlook.office.com",
    "outlook.office365.com",
    ".logic.azure.com",
    ".logic.azure.us",          # 政务云
)
_TIMEOUT_SECONDS = 10.0

# Adaptive Card 的容器样式，用来给整张卡带一条颜色边。
_SEVERITY_STYLE = {
    "critical": "attention",
    "high": "attention",
    "medium": "warning",
    "low": "accent",
    "info": "default",
}


class TeamsError(ChannelError):
    pass


def validate_webhook_url(url: str) -> None:
    raw = (url or "").strip()
    if not raw:
        raise ApiError("webhook_url_required")
    u = urlparse(raw)
    if u.scheme != "https":
        raise ApiError("webhook_must_be_https", channel="Teams")
    host = (u.hostname or "").lower()
    if not any(host == s.lstrip(".") or host.endswith(s) for s in ALLOWED_HOST_SUFFIXES):
        raise ApiError(
            "webhook_host_invalid", channel="Teams", host=host,
            expected="*.webhook.office.com 或 *.logic.azure.com",
        )


def render(payload: Payload) -> dict[str, Any]:
    """Adaptive Card。不需要转义 —— 值走的是 TextBlock 的 text 字段，Teams 按
    数据渲染，不解析成 markdown 链接；卡片结构本身也不是从字符串拼出来的，所以
    不存在「拼出一个假按钮」那条路。

    唯一要挡的是 `wrap`：不设它，长的规则名和主体值会被截断成一行。
    """
    body: list[dict[str, Any]] = [{
        "type": "TextBlock",
        "text": payload.heading,
        "weight": "Bolder",
        "size": "Medium",
        "wrap": True,
    }]
    if payload.fields:
        body.append({
            "type": "FactSet",
            "facts": [{"title": label, "value": value} for label, value in payload.fields],
        })
    body.append({
        "type": "TextBlock",
        "text": "RST Elastic AI Copilot",
        "isSubtle": True,
        "size": "Small",
        "wrap": True,
    })

    card: dict[str, Any] = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        # 1.4：Teams 桌面/移动端稳定支持的上限。写高了旧客户端整张卡不渲染。
        "version": "1.4",
        "body": [{
            "type": "Container",
            "style": _SEVERITY_STYLE.get(payload.severity, "default"),
            "bleed": True,
            "items": body,
        }],
    }
    if payload.link:
        card["actions"] = [
            {"type": "Action.OpenUrl", "title": "在产品中查看", "url": payload.link}
        ]

    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": card,
        }],
    }


async def send(
    webhook_url: str,
    body: dict[str, Any],
    *,
    secret: str | None = None,   # Teams webhook 无签名；形参保持同形
    verify_tls: bool = True,
) -> None:
    validate_webhook_url(webhook_url)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, verify=verify_tls) as client:
            resp = await client.post(webhook_url, json=body,
                                     headers={"Content-Type": "application/json"})
    except httpx.HTTPError as e:
        raise TeamsError(f"Teams 请求失败：{e}", retryable=True) from e

    # 2xx 即成功。旧连接器给 200 + "1"，Workflows 给 202 + 空 body —— 要求 body
    # 里有什么，两边必炸一边。
    if 200 <= resp.status_code < 300:
        return

    reason = (resp.text or "").strip()[:120]
    if resp.status_code >= 500:
        raise TeamsError(f"Teams HTTP {resp.status_code}: {reason}", retryable=True)
    if resp.status_code == 429:
        raise TeamsError(f"Teams 限流：{reason}", retryable=True)
    # 4xx：URL 作废、连接器被删、卡片结构不合法 —— 重试没有意义。
    raise TeamsError(f"Teams HTTP {resp.status_code}: {reason}", retryable=False)
