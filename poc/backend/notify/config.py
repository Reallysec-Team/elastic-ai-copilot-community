"""Notify configuration: Feishu targets + report schedule, persisted in ES.

Single doc (id="config") in ``.rst_copilot_notify_config``:

    {
      "schedule": {"periods": [...], "hour": 9, "tz": "Asia/Shanghai"},
      "alert_severity_threshold": "high",     # global default for alert push
      "targets": [ {target}, ... ]
    }

target = {id, channel, name, periods[], alert_severity_threshold, enabled,
          created_at, updated_at,
          # channel="feishu": webhook_url + secret_enc
          # channel="email":  recipients[]（SMTP 服务器是全局的，见下）}

smtp = {host, port, security, username, password_enc, from_addr, from_name}
  —— 全局一份，不跟着目标走：客户改邮箱密码时不该改 N 个目标。

Secrets are Fernet-encrypted at rest (``secret_enc``); the redacted read used by
the UI never returns them (only ``secret_set: bool``).
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import Any

from elasticsearch import NotFoundError

from ..es_client import get_es
from ..reports import PERIODS
from . import secret_box
from . import channels
from ..api_errors import ApiError

logger = logging.getLogger("rst.notify.config")

DEFAULT_INDEX = ".rst_copilot_notify_config"
_DOC_ID = "config"

SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]
_DEFAULT_THRESHOLD = "high"

_DEFAULT_CONFIG: dict[str, Any] = {
    "schedule": {"periods": [], "hour": 9, "tz": "Asia/Shanghai"},
    "alert_severity_threshold": _DEFAULT_THRESHOLD,
    "targets": [],
    "smtp": {},
}

CHANNELS = channels.KINDS
_DEFAULT_CHANNEL = "feishu"  # 老目标没有 channel 字段 —— 那时只有飞书

# 邮箱地址：不做 RFC 5322 全解析，只挡住明显不是地址的输入。真正的判据是
# 「发得出去吗」，那由发信时的 SMTP 应答回答，不是这里。
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SMTP_SECURITY = ("none", "starttls", "ssl")


def _index() -> str:
    return (os.environ.get("RST_NOTIFY_CONFIG_INDEX") or DEFAULT_INDEX).strip() or DEFAULT_INDEX


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sev_rank(sev: str | None) -> int:
    try:
        return SEVERITY_ORDER.index((sev or "").lower())
    except ValueError:
        return SEVERITY_ORDER.index(_DEFAULT_THRESHOLD)


# ---- raw doc read/write (with optimistic concurrency) --------------------

async def _read_doc(*, strict: bool = True) -> tuple[dict[str, Any], int | None, int | None]:
    """读配置文档。写路径上**只有「确实没有」才回默认值**。

    原来这里是 `except Exception` 一把兜住，所有读失败都当成「文档不存在」——
    于是一次 ES 超时或节点重启，加上管理员正好在界面上点了保存，写出去的就是
    一次不带 CAS 的全量覆盖：已配的投递目标、SMTP 凭据、订阅周期一起没了，
    而且因为 seq_no 是 None，ES 侧也拦不住。conversation.py 在同样的位置是对的
    （读失败直接 return，不写）。
    """
    es = get_es()
    try:
        resp = await es.get(index=_index(), id=_DOC_ID)
    except NotFoundError:
        return {**_DEFAULT_CONFIG, "targets": []}, None, None
    except Exception as e:  # noqa: BLE001
        if _is_missing_index(e):
            return {**_DEFAULT_CONFIG, "targets": []}, None, None
        # 读不到就不知道现在有什么，这时候写等于清空 —— 让调用方失败（→ 5xx），
        # 比悄悄覆盖强。纯读的调用方（界面上展示配置）传 strict=False：那条路上
        # 退回默认值只是少显示几行，不会毁数据。
        logger.warning("notify_config_read_failed", extra={"error": str(e)[:200]})
        if strict:
            raise
        return {**_DEFAULT_CONFIG, "targets": []}, None, None
    src = resp.body.get("_source") or {}
    cfg = {**_DEFAULT_CONFIG, **src}
    cfg.setdefault("targets", [])
    return cfg, resp.body.get("_seq_no"), resp.body.get("_primary_term")


def _is_missing_index(e: Exception) -> bool:
    """索引还没建出来（第一次用）也算「确实没有」。"""
    text = str(e).lower()
    return "index_not_found" in text or "no such index" in text


async def _write_doc(cfg: dict[str, Any], seq_no: int | None, primary_term: int | None) -> None:
    es = get_es()
    kwargs: dict[str, Any] = {"index": _index(), "id": _DOC_ID, "document": cfg, "refresh": "wait_for"}
    if seq_no is not None and primary_term is not None:
        kwargs["if_seq_no"] = seq_no
        kwargs["if_primary_term"] = primary_term
    await es.index(**kwargs)


# ---- validation ----------------------------------------------------------

def _validate_periods(periods: Any) -> list[str]:
    if not isinstance(periods, list):
        raise ApiError("periods_not_array")
    out = []
    for p in periods:
        if p not in PERIODS:
            raise ApiError("unknown_period", value=p, choices=', '.join(PERIODS))
        if p not in out:
            out.append(p)
    return out


def _validate_recipients(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [x for x in re.split(r"[,;\s]+", raw) if x]
    if not isinstance(raw, list) or not raw:
        raise ApiError("recipients_required")
    out: list[str] = []
    for addr in raw:
        addr = str(addr).strip()
        if not _EMAIL_RE.match(addr):
            raise ApiError("recipient_invalid", value=repr(addr))
        if addr not in out:
            out.append(addr)
    return out


def _validate_target_input(t: dict[str, Any], *, url_optional: bool = False) -> None:
    name = (t.get("name") or "").strip()
    if not name:
        raise ApiError("name_required")
    channel = (t.get("channel") or _DEFAULT_CHANNEL).lower()
    if channel not in CHANNELS:
        raise ApiError("unknown_channel", value=channel, choices=', '.join(CHANNELS))
    if channel == "email":
        _validate_recipients(t.get("recipients"))
    elif url_optional and not (t.get("webhook_url") or "").strip():
        # 编辑一个已有目标时留空 = 沿用已存的那条 URL。界面读不到明文（它是凭据，
        # 见下面的 _redact_target），所以「改个名字」这种编辑必须允许不重填 URL。
        pass
    else:
        # 每个 IM 有自己的域名白名单和路径要求 —— 交给渠道自己判，config 不该
        # 知道钉钉的 webhook 长什么样。
        channels.validate_target(channel, t)
    _validate_periods(t.get("periods", []))
    thr = (t.get("alert_severity_threshold") or _DEFAULT_THRESHOLD).lower()
    if thr not in SEVERITY_ORDER:
        raise ApiError("severity_threshold_invalid", value=thr)


def _webhook_host(url: str) -> str:
    """只留主机名。界面上要的是「这条发去哪个平台」，那一段不是凭据。"""
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def _redact_target(t: dict[str, Any]) -> dict[str, Any]:
    """给 HTTP 用的那一份：密钥和 webhook URL 都不出去。

    企业微信 / Slack / Teams 的鉴权就是 URL 里那个 key —— 对这三个渠道，
    webhook_url **本身就是凭据**，和飞书的签名密钥是同一档东西。原来它明文存在
    ES 的配置文档里，也明文经 HTTP 回给界面。
    """
    out = {k: v for k, v in t.items() if k not in ("secret_enc", "webhook_url_enc", "webhook_url")}
    out["secret_set"] = bool(t.get("secret_enc"))
    url = _target_webhook_url(t)
    out["webhook_set"] = bool(url)
    out["webhook_host"] = _webhook_host(url)
    # 密文还在、这台网关的钥匙打不开(重装 / 换了 state 卷)。界面上「已设置密钥」
    # 会一直是绿的,直到某次投递失败才知道 —— 明说。
    out["secret_stale"] = secret_box.is_stale(t.get("secret_enc", "")) or (
        bool(t.get("webhook_url_enc")) and not url
    )
    return out


def _target_webhook_url(t: dict[str, Any]) -> str:
    """解出这条目标的 webhook URL。

    `webhook_url_enc` 是现在的存法；`webhook_url` 是加密之前留下的明文，读的时候
    仍然认 —— 存量不会因为升级一次就发不出去。写路径只写密文，加上启动时那趟
    `migrate_plaintext_webhook_urls()`，明文会自己消失。
    """
    enc = t.get("webhook_url_enc")
    if enc:
        return secret_box.decrypt(str(enc))
    return str(t.get("webhook_url") or "")


# ---- public API ----------------------------------------------------------

async def get_config(*, redact: bool = True) -> dict[str, Any]:
    cfg, _, _ = await _read_doc(strict=False)
    targets = [{**t, "channel": t.get("channel") or _DEFAULT_CHANNEL} for t in cfg.get("targets", [])]
    cfg = {**cfg, "targets": [_redact_target(t) for t in targets] if redact else targets,
           "smtp": _redact_smtp(cfg.get("smtp") or {}) if redact else (cfg.get("smtp") or {})}
    return cfg


async def save_schedule(schedule: dict[str, Any]) -> dict[str, Any]:
    periods = _validate_periods(schedule.get("periods", []))
    try:
        hour = int(schedule.get("hour", 9))
    except (TypeError, ValueError):
        raise ApiError("hour_not_int")
    if not 0 <= hour <= 23:
        raise ApiError("hour_out_of_range")
    tz = (schedule.get("tz") or "Asia/Shanghai").strip() or "Asia/Shanghai"
    cfg, seq, term = await _read_doc()
    cfg["schedule"] = {"periods": periods, "hour": hour, "tz": tz}
    if "alert_severity_threshold" in schedule:
        thr = str(schedule["alert_severity_threshold"]).lower()
        if thr in SEVERITY_ORDER:
            cfg["alert_severity_threshold"] = thr
    await _write_doc(cfg, seq, term)
    return await get_config()


async def upsert_target(target: dict[str, Any]) -> dict[str, Any]:
    """Create (no id) or update (existing id) a Feishu target. A blank/absent
    ``secret`` on update keeps the stored secret; ``secret=""`` explicitly clears
    it only when the caller sends ``clear_secret: true``."""
    cfg, seq, term = await _read_doc()
    targets = cfg.get("targets", [])

    tid = (target.get("id") or "").strip()
    # 编辑既有目标时 webhook_url 可以留空（沿用已存的）；新建必须给。
    _validate_target_input(target, url_optional=bool(tid))
    now = _now()
    channel = (target.get("channel") or _DEFAULT_CHANNEL).lower()
    record = {
        "channel": channel,
        "name": target["name"].strip(),
        "periods": _validate_periods(target.get("periods", [])),
        "alert_severity_threshold": (target.get("alert_severity_threshold") or _DEFAULT_THRESHOLD).lower(),
        "enabled": bool(target.get("enabled", True)),
    }
    if channel == "email":
        record["recipients"] = _validate_recipients(target.get("recipients"))

    # 老目标没有 channel，读的时候按飞书兜底 —— 存量不改写。
    for t in targets:
        t.setdefault("channel", _DEFAULT_CHANNEL)

    idx = next((i for i, t in enumerate(targets) if t.get("id") == tid), -1) if tid else -1
    if idx >= 0:
        existing = targets[idx]
        # Secret handling: new secret → re-encrypt; clear_secret → wipe; else keep.
        if target.get("secret"):
            record["secret_enc"] = secret_box.encrypt(str(target["secret"]))
        elif target.get("clear_secret"):
            record["secret_enc"] = ""
        else:
            record["secret_enc"] = existing.get("secret_enc", "")
        if channel != "email":
            fresh_url = (target.get("webhook_url") or "").strip()
            record["webhook_url_enc"] = (
                secret_box.encrypt(fresh_url)
                if fresh_url
                else existing.get("webhook_url_enc")
                or secret_box.encrypt(str(existing.get("webhook_url") or ""))
            )
        record["id"] = tid
        record["created_at"] = existing.get("created_at", now)
        record["updated_at"] = now
        targets[idx] = record
    else:
        record["id"] = secrets.token_hex(6)
        if channel != "email":
            record["webhook_url_enc"] = secret_box.encrypt(target["webhook_url"].strip())
        record["secret_enc"] = secret_box.encrypt(str(target["secret"])) if target.get("secret") else ""
        record["created_at"] = now
        record["updated_at"] = now
        targets.append(record)

    cfg["targets"] = targets
    await _write_doc(cfg, seq, term)
    return await get_config()


async def delete_target(target_id: str) -> bool:
    cfg, seq, term = await _read_doc()
    targets = cfg.get("targets", [])
    remaining = [t for t in targets if t.get("id") != target_id]
    if len(remaining) == len(targets):
        return False
    cfg["targets"] = remaining
    await _write_doc(cfg, seq, term)
    return True


async def get_target_raw(target_id: str) -> dict[str, Any] | None:
    """Full target incl. decrypted ``secret`` (for outbox/test-send). Never
    exposed via HTTP."""
    cfg, _, _ = await _read_doc(strict=False)
    for t in cfg.get("targets", []):
        if t.get("id") == target_id:
            return {**t, "secret": secret_box.decrypt(t.get("secret_enc", "")),
                    "webhook_url": _target_webhook_url(t)}
    return None


async def targets_for_period(period: str) -> list[dict[str, Any]]:
    """Enabled targets bound to ``period`` (secrets decrypted)."""
    cfg, _, _ = await _read_doc(strict=False)
    out = []
    for t in cfg.get("targets", []):
        if t.get("enabled") and period in (t.get("periods") or []):
            out.append({**t, "secret": secret_box.decrypt(t.get("secret_enc", "")),
                        "webhook_url": _target_webhook_url(t)})
    return out


async def targets_for_alert(severity: str) -> list[dict[str, Any]]:
    """Enabled targets whose per-target threshold is <= the alert severity."""
    cfg, _, _ = await _read_doc(strict=False)
    rank = sev_rank(severity)
    out = []
    for t in cfg.get("targets", []):
        if not t.get("enabled"):
            continue
        if sev_rank(t.get("alert_severity_threshold")) <= rank:
            out.append({**t, "secret": secret_box.decrypt(t.get("secret_enc", "")),
                        "webhook_url": _target_webhook_url(t)})
    return out


# ---- SMTP（全局一份） ------------------------------------------------------

def _redact_smtp(smtp: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in smtp.items() if k != "password_enc"}
    out["password_set"] = bool(smtp.get("password_enc"))
    out["password_stale"] = secret_box.is_stale(smtp.get("password_enc", ""))
    return out


def _validate_smtp(smtp: dict[str, Any]) -> None:
    if not (smtp.get("host") or "").strip():
        raise ApiError("smtp_host_required")
    try:
        port = int(smtp.get("port") or 0)
    except (TypeError, ValueError):
        raise ApiError("smtp_port_not_int")
    if not 1 <= port <= 65535:
        raise ApiError("smtp_port_out_of_range")
    sec = (smtp.get("security") or "starttls").lower()
    if sec not in _SMTP_SECURITY:
        raise ApiError("smtp_security_invalid", value=sec, choices=', '.join(_SMTP_SECURITY))
    frm = (smtp.get("from_addr") or "").strip()
    if not _EMAIL_RE.match(frm):
        raise ApiError("smtp_from_invalid", value=repr(frm))


async def save_smtp(smtp: dict[str, Any]) -> dict[str, Any]:
    """写全局 SMTP 配置。密码沿用目标密钥那套 Fernet 加密，空密码 = 保持原样
    （界面回传打码占位符时不该把密码清掉），显式 clear_password 才清。"""
    _validate_smtp(smtp)
    cfg, seq, term = await _read_doc()
    existing = cfg.get("smtp") or {}
    record = {
        "host": smtp["host"].strip(),
        "port": int(smtp["port"]),
        "security": (smtp.get("security") or "starttls").lower(),
        "username": (smtp.get("username") or "").strip(),
        "from_addr": smtp["from_addr"].strip(),
        "from_name": (smtp.get("from_name") or "").strip(),
    }
    if smtp.get("password"):
        record["password_enc"] = secret_box.encrypt(str(smtp["password"]))
    elif smtp.get("clear_password"):
        record["password_enc"] = ""
    else:
        record["password_enc"] = existing.get("password_enc", "")
    cfg["smtp"] = record
    await _write_doc(cfg, seq, term)
    return await get_config()


async def get_smtp_raw() -> dict[str, Any]:
    """含明文密码，只给发信路径用，绝不经 HTTP 出去。"""
    cfg, _, _ = await _read_doc(strict=False)
    smtp = dict(cfg.get("smtp") or {})
    smtp["password"] = secret_box.decrypt(smtp.get("password_enc", ""))
    return smtp


async def migrate_plaintext_webhook_urls() -> int:
    """把存量目标里的明文 `webhook_url` 换成密文，返回改了几条。

    幂等：已经是密文的跳过。走的是和其它写一样的 CAS（`_write_doc` 带 seq/term），
    所以和管理员同时在界面上保存不会互相盖掉 —— 冲突了这一趟就不改，下次启动
    再来。
    """
    cfg, seq, term = await _read_doc()
    targets = cfg.get("targets", [])
    changed = 0
    for t in targets:
        if t.get("webhook_url_enc") or not t.get("webhook_url"):
            continue
        t["webhook_url_enc"] = secret_box.encrypt(str(t["webhook_url"]))
        t.pop("webhook_url", None)
        changed += 1
    if changed:
        cfg["targets"] = targets
        await _write_doc(cfg, seq, term)
        logger.warning("webhook_urls_encrypted", extra={"count": changed})
    return changed
