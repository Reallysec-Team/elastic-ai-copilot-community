"""钉钉自定义机器人 webhook。

与飞书同形（带签名的 webhook），差别都在细节上，而这些细节正是「按平台名抄一遍」
会抄错的地方：

  - 端点：oapi.dingtalk.com/robot/send?access_token=…（token 在 URL 里）
  - 消息：{"msgtype":"markdown","markdown":{"title":…,"text":…}}
    标题只在手机推送的通知栏里出现，正文里看不到，所以正文要自带一遍标题
  - 签名（机器人开启「加签」时）：
        string_to_sign = f"{timestamp}\\n{secret}"
        sign = urlencode(base64(HMAC_SHA256(key=secret, msg=string_to_sign)))
    注意与飞书相反 —— 飞书拿 string_to_sign 当密钥、空串当消息，钉钉是拿 secret
    当密钥、string_to_sign 当消息，且 timestamp 是**毫秒**，两者都放在 query
    而不是 body 里
  - 成功判据：HTTP 200 且 body 里 errcode == 0（失败也常常是 200）
  - 安全设置若选的是「自定义关键词」，消息必须包含那个词 —— 页脚固定带 RST，
    与飞书同一处理
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
import urllib.parse
from typing import Any
from urllib.parse import urlparse

import httpx

from .errors import ChannelError
from .payload import Payload
from ..api_errors import ApiError

logger = logging.getLogger("rst.notify.dingtalk")

ALLOWED_HOSTS = ("oapi.dingtalk.com",)
_TIMEOUT_SECONDS = 10.0

# 钉钉 markdown 不支持颜色，用一个前缀符号带出严重度 —— 群里刷屏时靠它扫。
_SEVERITY_MARK = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🔵",
    "info": "⚪",
}


class DingtalkError(ChannelError):
    pass


def validate_webhook_url(url: str) -> None:
    """只允许钉钉自己的域名。URL 是管理员填的，但它仍然是一个跨信任边界的
    出站 POST —— 不限制就等于给了一个任意地址的转发器（SSRF）。"""
    raw = (url or "").strip()
    if not raw:
        raise ApiError("webhook_url_required")
    u = urlparse(raw)
    if u.scheme != "https":
        raise ApiError("webhook_must_be_https", channel="钉钉")
    if u.hostname not in ALLOWED_HOSTS:
        raise ApiError("webhook_host_invalid", channel="钉钉", host=u.hostname, expected=ALLOWED_HOSTS[0])
    if not u.path.startswith("/robot/send"):
        raise ApiError("dingtalk_path_invalid")


def sign(secret: str, timestamp_ms: str) -> str:
    """钉钉加签。与飞书的密钥/消息正好相反，抄错了只会得到 310000 一句
    「sign not match」，没有别的线索。"""
    string_to_sign = f"{timestamp_ms}\n{secret}"
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"),
                      hashlib.sha256).digest()
    return urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))


def _esc(value: Any) -> str:
    """转义 markdown 元字符。钉钉正文是 markdown，规则名和主体值可能是攻击者
    写进日志的东西 —— 不转义就能在群里伪造一条带链接的消息。

    表里不含 `_`：安全日志里的账号名、主机名、索引名全是下划线（svc_backup、
    .rst_copilot_audit），转了之后群里看到的是 svc\\_backup，而这正是这个产品
    最主要的内容。下划线最坏把一段字变成斜体，方括号和圆括号却能伪造一个链接 ——
    两者的代价差着一个量级。
    """
    s = str(value)
    for ch in "\\`*[]()":
        s = s.replace(ch, "\\" + ch)
    return s


def render(payload: Payload) -> dict[str, Any]:
    mark = _SEVERITY_MARK.get(payload.severity, "")
    lines = [f"### {mark} {_esc(payload.heading)}", ""]
    lines += [f"- **{_esc(label)}**：{_esc(value)}" for label, value in payload.fields]
    if payload.link:
        # 钉钉的按钮要用 actionCard，为一个链接换一种消息类型不值得；行内链接
        # 在手机和桌面端都能点。
        lines += ["", f"[在产品中查看]({payload.link})"]
    lines += ["", "> RST Elastic AI Copilot"]
    return {
        "msgtype": "markdown",
        # 标题只出现在推送通知栏里，正文里看不到 —— 所以上面正文自带了一遍。
        "markdown": {"title": payload.heading, "text": "\n".join(lines)},
    }


async def send(
    webhook_url: str,
    body: dict[str, Any],
    *,
    secret: str | None = None,
    verify_tls: bool = True,
    timestamp_ms: str | None = None,
) -> None:
    """POST 一条消息。失败一律抛 DingtalkError 并带上 retryable。

    ``timestamp_ms`` 供测试注入；生产用当前毫秒。
    """
    validate_webhook_url(webhook_url)
    url = webhook_url
    if secret:
        ts = timestamp_ms or str(int(time.time() * 1000))
        joiner = "&" if urlparse(url).query else "?"
        url = f"{url}{joiner}timestamp={ts}&sign={sign(secret, ts)}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, verify=verify_tls) as client:
            resp = await client.post(url, json=body,
                                     headers={"Content-Type": "application/json"})
    except httpx.HTTPError as e:
        raise DingtalkError(f"钉钉请求失败：{e}", retryable=True) from e

    if resp.status_code >= 500:
        raise DingtalkError(f"钉钉 HTTP {resp.status_code}", retryable=True)
    if resp.status_code >= 400:
        raise DingtalkError(f"钉钉 HTTP {resp.status_code}", retryable=resp.status_code == 429)

    try:
        data = resp.json()
    except ValueError:
        raise DingtalkError("钉钉返回的不是 JSON", retryable=True)

    code = data.get("errcode")
    if code == 0:
        return
    msg = str(data.get("errmsg") or "")
    # 130101 = 发送频率受限；其余（token 失效、签名不符、关键词不匹配、被移出群）
    # 都是配置问题，重试没有意义。
    raise DingtalkError(f"钉钉 errcode={code}: {msg}", retryable=code == 130101)
