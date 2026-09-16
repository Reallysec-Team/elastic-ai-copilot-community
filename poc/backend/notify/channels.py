"""渠道派发表 —— 全系统唯一一处知道「有哪几个渠道」的地方。

生产者产中立事件（``payload``），outbox 负责队列，这里负责「用哪种方式画、往哪儿
发」。加一个渠道 = 写一个 provider 模块 + 在下面这张表里加一行；outbox、配置校验、
路由都不用动。

四个渠道其实只有两种形态：

    webhook   飞书 / 钉钉 / 企业微信 —— POST 一个 JSON，各自的 body 模板与签名
    smtp      邮件 —— 连接、附件、收件人列表

按形态而不是按平台名切：Teams 和 Slack 后来确实是各加一个 provider 模块就进来了，
outbox、配置校验、路由一行没动。
"""

from __future__ import annotations

from typing import Any

from . import dingtalk, email, feishu, slack, teams, wecom
from .errors import ChannelError
from .payload import Payload

#: 渠道 → (渲染, 发送, 校验)。send 统一签名 ``(target, body)``。
_WEBHOOK_PROVIDERS = {
    "feishu": feishu,
    "dingtalk": dingtalk,
    "wecom": wecom,
    "teams": teams,
    "slack": slack,
}

KINDS = ("feishu", "dingtalk", "wecom", "teams", "slack", "email")

#: 界面上的名字。后端也留一份，是因为投递失败的日志和审计事件里也要写渠道名。
LABELS = {
    "feishu": "飞书",
    "dingtalk": "钉钉",
    "wecom": "企业微信",
    "teams": "Teams",
    "slack": "Slack",
    "email": "邮件",
}


def normalize(kind: str | None) -> str:
    """兜底成 feishu —— 老目标和老投递文档没有 channel 字段，那时只有飞书。"""
    k = (kind or "").strip().lower()
    return k if k in KINDS else "feishu"


def render(kind: str, payload: Payload) -> dict[str, Any]:
    kind = normalize(kind)
    if kind == "email":
        return email.render(payload)
    return _WEBHOOK_PROVIDERS[kind].render(payload)


async def send(kind: str, target: dict[str, Any], body: dict[str, Any]) -> None:
    """把渲染好的 body 发出去。失败一律是 ``ChannelError``，带 retryable。

    ``target`` 是投递文档或配置里的目标记录，两者字段同名（webhook_url /
    secret / recipients），所以这一层不需要知道调用方是谁。
    """
    kind = normalize(kind)
    if kind == "email":
        await email.send(target.get("recipients") or [], body)
        return
    provider = _WEBHOOK_PROVIDERS[kind]
    await provider.send(
        target.get("webhook_url") or "",
        body,
        secret=(target.get("secret") or None),
    )


def validate_target(kind: str, target: dict[str, Any]) -> None:
    """保存目标前的形状校验。抛 ValueError（路由转 400）。"""
    kind = normalize(kind)
    if kind == "email":
        return  # 收件人由 config._validate_recipients 校验
    _WEBHOOK_PROVIDERS[kind].validate_webhook_url(target.get("webhook_url", ""))


def supports_signature(kind: str) -> bool:
    """这个渠道有没有「签名密钥」这一项 —— 界面据此决定要不要显示那个输入框。

    六个里只有飞书和钉钉有。企业微信、Teams、Slack 的鉴权都是 URL 本身 ——
    Slack 的 signing secret 是给入站请求验签的，跟出站 webhook 无关。
    """
    return normalize(kind) in ("feishu", "dingtalk")


__all__ = [
    "KINDS", "LABELS", "ChannelError",
    "normalize", "render", "send", "validate_target", "supports_signature",
]
