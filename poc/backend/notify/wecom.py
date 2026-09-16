"""企业微信群机器人 webhook。

四个 IM 里最简单的一个，也正因如此有一处值得写下来：**它没有签名**，鉴权全靠
URL 里那个 key。所以这条 webhook URL 本身就是凭据 —— 泄露等于任何人都能往那个群
里发消息。它和飞书的 secret 一样按密文存（`webhook_url` 字段目前是明文存的，这是
个已知差距，见下）。

  - 端点：qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…
  - 消息：{"msgtype":"markdown","markdown":{"content":…}}
  - 成功判据：HTTP 200 且 errcode == 0
  - markdown 支持有限：不支持表格、图片，支持 <font color="warning"> 这种内联
    着色（只有三种颜色：info 绿 / comment 灰 / warning 橙）

已知差距：webhook_url 与飞书目标一样明文存在 ES 的配置文档里。对飞书那是「地址 +
另存密钥」，对企业微信这就是凭据本身。要真正对齐，webhook_url 也该进 secret_box，
那是一次涉及存量数据的迁移，不在这次范围里 —— 先把它写在这里，别让它悄悄消失。
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from .errors import ChannelError
from .payload import Payload
from ..api_errors import ApiError

logger = logging.getLogger("rst.notify.wecom")

ALLOWED_HOSTS = ("qyapi.weixin.qq.com",)
_TIMEOUT_SECONDS = 10.0

# 企业微信只认这三个颜色名。
_SEVERITY_COLOR = {
    "critical": "warning",
    "high": "warning",
    "medium": "comment",
    "low": "comment",
    "info": "info",
}


class WecomError(ChannelError):
    pass


def validate_webhook_url(url: str) -> None:
    raw = (url or "").strip()
    if not raw:
        raise ApiError("webhook_url_required")
    u = urlparse(raw)
    if u.scheme != "https":
        raise ApiError("webhook_must_be_https", channel="企业微信")
    if u.hostname not in ALLOWED_HOSTS:
        raise ApiError("webhook_host_invalid", channel="企业微信", host=u.hostname, expected=ALLOWED_HOSTS[0])
    if "key=" not in (u.query or ""):
        raise ApiError("wecom_key_missing")


def _esc(value: Any) -> str:
    """转义 markdown 元字符 + 尖括号。尖括号尤其要转：企业微信的 markdown 认
    `<font color=...>`，不转义就等于让日志里的内容自带排版和着色。

    与钉钉同理，表里不含 `_` —— 账号名和索引名全是下划线，转了反而看不清。
    """
    s = str(value)
    for ch in "\\`*[]()":
        s = s.replace(ch, "\\" + ch)
    return s.replace("<", "&lt;").replace(">", "&gt;")


def render(payload: Payload) -> dict[str, Any]:
    color = _SEVERITY_COLOR.get(payload.severity, "info")
    lines = [f'**<font color="{color}">{_esc(payload.heading)}</font>**', ""]
    lines += [f"> **{_esc(label)}**：{_esc(value)}" for label, value in payload.fields]
    if payload.link:
        lines += ["", f"[在产品中查看]({payload.link})"]
    lines += ["", "RST Elastic AI Copilot"]
    return {"msgtype": "markdown", "markdown": {"content": "\n".join(lines)}}


async def send(
    webhook_url: str,
    body: dict[str, Any],
    *,
    secret: str | None = None,   # 企业微信不用签名；保留形参让四个渠道同形
    verify_tls: bool = True,
) -> None:
    validate_webhook_url(webhook_url)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, verify=verify_tls) as client:
            resp = await client.post(webhook_url, json=body,
                                     headers={"Content-Type": "application/json"})
    except httpx.HTTPError as e:
        raise WecomError(f"企业微信请求失败：{e}", retryable=True) from e

    if resp.status_code >= 500:
        raise WecomError(f"企业微信 HTTP {resp.status_code}", retryable=True)
    if resp.status_code >= 400:
        raise WecomError(f"企业微信 HTTP {resp.status_code}", retryable=resp.status_code == 429)

    try:
        data = resp.json()
    except ValueError:
        raise WecomError("企业微信返回的不是 JSON", retryable=True)

    code = data.get("errcode")
    if code == 0:
        return
    msg = str(data.get("errmsg") or "")
    # 45009 = 接口调用超过限制（每分钟 20 条）。其余多为 key 失效 / 参数错误。
    raise WecomError(f"企业微信 errcode={code}: {msg}", retryable=code == 45009)
