"""Notify configuration + delivery-status API（报告 / 告警的对外投递）。

All paths under /api/notify/*. Blanket auth is applied by middleware; these
routes only add their own input validation (ValueError → 400).

读开放、写要管理员。中间件那道闸只按 HTTP 方法判，它挡的是 viewer —— analyst
的 PUT/POST/DELETE 是放行的，管理面得路由自己拦。这一组不拦的后果很具体：
`PUT /api/notify/smtp` 只传 host 不传 password 时，已存的 `password_enc` 会原样
留着（见 notify/config.py 的 else 分支），于是改一个 host 就能让下一封报告邮件
带着客户的 SMTP 凭据登录到别人的服务器上。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .auth import require_admin

from .notify import channels, config, outbox
from .notify.errors import ChannelError
from .notify import payload as payload_mod
from .api_errors import ApiError

router = APIRouter(tags=["notify"])


class ScheduleIn(BaseModel):
    periods: list[str] = []
    hour: int = 9
    tz: str = "Asia/Shanghai"
    alert_severity_threshold: str | None = None


class TargetIn(BaseModel):
    id: str | None = None
    # 老前端不传 channel —— 那时只有飞书，默认值保持它们能用。
    channel: str = "feishu"
    name: str
    # 飞书目标必填；邮件目标用 recipients。两者的校验在 config 里按 channel 分流。
    webhook_url: str = ""
    recipients: list[str] = []
    secret: str | None = None
    clear_secret: bool = False
    periods: list[str] = []
    alert_severity_threshold: str = "high"
    enabled: bool = True


class SmtpIn(BaseModel):
    host: str
    port: int = 587
    security: str = "starttls"
    username: str = ""
    password: str | None = None
    clear_password: bool = False
    from_addr: str
    from_name: str = ""


@router.get("/api/notify/config")
async def get_notify_config() -> dict[str, Any]:
    return await config.get_config(redact=True)


@router.put("/api/notify/schedule")
async def put_schedule(body: ScheduleIn, request: Request) -> dict[str, Any]:
    require_admin(request)
    try:
        return await config.save_schedule(body.model_dump())
    except ApiError:
        raise
    except ValueError as e:
        raise ApiError("invalid_request", reason=e)


@router.post("/api/notify/targets")
async def upsert_target(body: TargetIn, request: Request) -> dict[str, Any]:
    require_admin(request)
    try:
        return await config.upsert_target(body.model_dump())
    except ApiError:
        raise
    except ValueError as e:
        raise ApiError("invalid_request", reason=e)


@router.delete("/api/notify/targets/{target_id}")
async def delete_target(target_id: str, request: Request) -> dict[str, Any]:
    require_admin(request)
    ok = await config.delete_target(target_id)
    if not ok:
        raise ApiError("notify_target_not_found", 404)
    return await config.get_config(redact=True)


@router.put("/api/notify/smtp")
async def put_smtp(body: SmtpIn, request: Request) -> dict[str, Any]:
    require_admin(request)
    try:
        return await config.save_smtp(body.model_dump())
    except ApiError:
        raise
    except ValueError as e:
        raise ApiError("invalid_request", reason=e)


@router.post("/api/notify/deliveries/{delivery_id}/retry")
async def retry_delivery(delivery_id: str, request: Request) -> dict[str, Any]:
    """把一条投递重新排队。死信是这个接口存在的理由 —— webhook 被撤销、SMTP 密码
    改了，修好之后那几条报告不该只能靠客户自己去补。"""
    require_admin(request)
    ok = await outbox.requeue(delivery_id)
    if not ok:
        raise ApiError("delivery_not_retryable", 409)
    return {"ok": True}


@router.post("/api/notify/targets/{target_id}/test")
async def test_target(target_id: str, request: Request) -> dict[str, Any]:
    """Send a sample card immediately (synchronous) so the UI gets a live result.
    Bypasses the outbox — this is a connectivity probe, not a real delivery."""
    require_admin(request)
    target = await config.get_target_raw(target_id)
    if target is None:
        raise ApiError("notify_target_not_found", 404)
    kind = target.get("channel")
    event = payload_mod.from_alert({
        "severity": "info",
        "rule_name": "测试通知",
        "recommendation": "这是一条来自 RST Elastic AI Copilot 的测试消息，收到即链路正常。",
    })
    try:
        await channels.send(kind, target, channels.render(kind, event))
        return {"ok": True}
    except ChannelError as e:
        # 连不通是这个接口的正常答案之一，不是 500 —— 前端要拿这句话显示给人看。
        return {"ok": False, "error": str(e)}


@router.get("/api/notify/deliveries")
async def list_deliveries(kind: str | None = None, status: str | None = None,
                          ref: str | None = None, limit: int = 50) -> dict[str, Any]:
    items = await outbox.list_deliveries(kind=kind, status=status, ref=ref, limit=limit)
    return {"deliveries": items}
