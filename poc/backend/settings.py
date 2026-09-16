"""Runtime settings overlay.

Acts as a thin layer on top of `os.environ`. The flow is:

  1. .env loaded by dotenv (handled in main.py)
  2. settings.apply_overlay() reads `settings.yml` (if present) and copies
     each key into os.environ — overriding anything dotenv set
  3. Existing modules keep reading from os.environ as before

When the user edits a setting via /api/settings, we:
  - patch os.environ in-place
  - write settings.yml so the change survives gateway restart
  - reset the affected module singletons (index_whitelist, audit sinks,
     llm_router, field_masking)

We deliberately do NOT touch llm_providers.yml or .env — those have their
own ownership story. Settings here is for the small set of operational
config the customer admin should be able to flip from the web UI.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

import yaml
from .api_errors import ApiError

logger = logging.getLogger("rst.settings")

DEFAULT_PATH = Path(__file__).parent.parent / "settings.yml"

# Maps the JSON-friendly key the UI sends to the env var existing modules read.
# Keys are flat with `.` separators on the JSON side, env vars are SCREAMING.
ENV_MAPPING: dict[str, str] = {
    # Elasticsearch connection. Owned by the setup wizard so a fresh install is
    # pointed at the customer's cluster from the browser instead of a hand-edited
    # .env — the settings overlay lives on disk, not in ES, so there is no
    # bootstrap deadlock in configuring ES through it.
    "es.url": "ES_URL",
    "es.user": "ES_USER",
    "es.password": "ES_PASSWORD",
    "es.verify_certs": "RST_ES_VERIFY_CERTS",
    "es.ca_cert": "RST_ES_CA_CERT",
    "engine": "RST_ENGINE",
    "index_whitelist": "RST_INDEX_WHITELIST",
    "masking_mode": "RST_MASKING_MODE",
    "audit.enabled": "RST_AUDIT_ENABLED",
    "audit.index": "RST_AUDIT_INDEX",
    "audit.syslog_url": "RST_AUDIT_SYSLOG_URL",
    "audit.webhook_url": "RST_AUDIT_WEBHOOK_URL",
    "audit.webhook_headers": "RST_AUDIT_WEBHOOK_HEADERS",
    "audit.tls_verify": "RST_AUDIT_TLS_VERIFY",
    # Real-time alert ingest (source A poll tail + source B webhook secret)
    "alerts.ingest_index": "RST_ALERT_INGEST_INDEX",
    "alerts.ingest_interval": "RST_ALERT_INGEST_INTERVAL_SECONDS",
    "alerts.webhook_secret": "RST_ALERT_WEBHOOK_SECRET",
}

# Keys whose values should be masked when serving GET /api/settings.
#
# 两个 URL 也在里面：对 Slack / 飞书 / 企业微信这类目标，webhook URL 本身就是
# 凭据 —— 拿到它就能往客户的审计通道里灌入伪造事件，不需要另外的密钥。
# 前端已经会处理 `<set · N chars>` 这个哨兵值（见 RealtimeAlertsPage 的
# SENTINEL_PREFIX 和 useSettingsDraft 的差量提交），所以加进来是闭合的。
SENSITIVE_KEYS = {
    "audit.webhook_headers",
    "audit.webhook_url",
    "audit.syslog_url",
    "alerts.webhook_secret",
    "es.password",
}


# settings.yml 落在 state 卷上，这五个值以前是明文躺在里面的。加密用的是
# notify 那套现成的 Fernet 盒子（密钥同样在 state 卷的 .rst_secret_key）——
# 密钥和密文同卷，爆炸半径没变大，换来的是「拿到一份 settings.yml 拷贝的人
# 读不到 ES 口令 / webhook 凭据」。
#
# 存量明文照读不误（没有前缀就是明文），启动时 apply_overlay 顺手把它们改写成
# 密文，幂等。密钥丢了（卷重建、RST_SECRET_KEY 换了）解不开时按「没设置」处理：
# 环境变量为空、界面上显示未设置，管理员重填一次即可 —— 好过把密文当口令发给 ES。
_ENC_PREFIX = "enc:v1:"


def _decrypt_value(key: str, value: Any) -> Any:
    if key not in SENSITIVE_KEYS or not isinstance(value, str):
        return value
    if not value.startswith(_ENC_PREFIX):
        return value  # 存量明文
    from .notify import secret_box

    plain = secret_box.decrypt(value[len(_ENC_PREFIX):])
    if not plain:
        logger.warning(f"settings value could not be decrypted, treating as unset: {key}")
    return plain


def _encrypt_value(key: str, value: Any) -> Any:
    if key not in SENSITIVE_KEYS or not isinstance(value, str) or not value.strip():
        return value
    if value.startswith(_ENC_PREFIX):
        return value  # 已是密文（合并写回时原样带过，不重复加密、也不因解不开而丢失）
    from .notify import secret_box

    return _ENC_PREFIX + secret_box.encrypt(value)


def tz_name() -> str:
    """操作者配的那个字符串（`RST_TIMEZONE`），没配就是 "UTC"。

    接口回给界面的是这个原样值，不是 `str(timezone(...))` 出来的 "UTC+08:00" ——
    后者跟 .env 里写的对不上，运维照着排查会先怀疑自己配错了。
    """
    return os.environ.get("RST_TIMEZONE", "").strip() or "UTC"


def product_tz() -> tzinfo:
    """部署所在时区（`RST_TIMEZONE`）。读不懂就按 UTC。

    「今天」在这个产品里是有主的：提示词按它跟模型解释日界，试用额度按它切日，
    报表巡检按它切日历边界。默认 UTC 对 UTC+8 的客户意味着额度在早上八点重置 ——
    界面上写着「每天」，实际不是他们的每天。

    固定偏移（`+08:00`）和 IANA 名字（`Asia/Shanghai`）都认。以前这里只认前者、
    只有报表调度器认后者，于是同一个部署里「今天」有两种算法 —— 夏令时地区的
    客户，报表和额度会在不同的时刻换日。
    """
    return parse_tz(os.environ.get("RST_TIMEZONE", ""), "RST_TIMEZONE")


def parse_tz(raw: str, var: str = "") -> tzinfo:
    """`+08:00` / `-05:30` / `Asia/Shanghai` → tzinfo。空或读不懂都回 UTC。"""
    raw = (raw or "").strip()
    if not raw:
        return timezone.utc
    try:
        if raw[0] in "+-":
            sign = -1 if raw[0] == "-" else 1
            hh, _, mm = raw[1:].partition(":")
            return timezone(sign * timedelta(hours=int(hh), minutes=int(mm or 0)))
        from zoneinfo import ZoneInfo

        return ZoneInfo(raw)
    except Exception as e:  # noqa: BLE001 — 配错了不能让巡检/额度停摆
        logger.warning(f"{var or 'timezone'}={raw!r} 读不懂（{e}），按 UTC 处理")
        return timezone.utc


def _yaml_path() -> Path:
    raw = os.environ.get("RST_SETTINGS_FILE", "").strip()
    return Path(raw) if raw else DEFAULT_PATH


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, path))
        else:
            out[path] = v
    return out


def _unflatten(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        cur = out
        parts = k.split(".")
        for p in parts[:-1]:
            if p not in cur or not isinstance(cur[p], dict):
                cur[p] = {}
            cur = cur[p]
        cur[parts[-1]] = v
    return out


def _load_yaml() -> dict[str, Any]:
    p = _yaml_path()
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"failed to read {p}: {e}")
        return {}


def _write_yaml(flat: dict[str, Any]) -> None:
    """Persist flat plaintext settings, encrypting the sensitive ones on the way out.

    临时文件 + `os.replace`，不是直接 `write_text`。这个文件里是 ES 口令、审计
    webhook 凭据、告警 webhook 密钥（都加了密，但截断之后一样解不开）——
    写到一半被 docker stop / OOM 打断，deployment 重启后回到「未配置」，而客户
    在界面上什么都不会看到。`main._atomic_write_yaml` 早就是这么写的。
    """
    p = _yaml_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    stored = {k: _encrypt_value(k, v) for k, v in flat.items()}
    body = yaml.safe_dump(_unflatten(stored), sort_keys=False, allow_unicode=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, p)


def _load_flat() -> dict[str, Any]:
    """settings.yml as flat keys with the sensitive values decrypted."""
    return {k: _decrypt_value(k, v) for k, v in _flatten(_load_yaml()).items()}


def _encrypt_plaintext_secrets() -> int:
    """Rewrite any sensitive value still stored in plaintext. Idempotent."""
    stored = _flatten(_load_yaml())
    plaintext = [
        k for k, v in stored.items()
        if k in SENSITIVE_KEYS and isinstance(v, str) and v.strip()
        and not v.startswith(_ENC_PREFIX)
    ]
    if not plaintext:
        return 0
    _write_yaml(stored)
    return len(plaintext)


def _migrate_legacy_file() -> None:
    """Move a pre-existing settings.yml onto the configured (persistent) path.

    The file used to default to a location inside the image, so an image swap
    threw the admin's settings away. It now lives under the state volume via
    RST_SETTINGS_FILE — and an existing deployment must carry its settings
    across that move rather than silently coming back up unconfigured.

    Copy, not move: the old file is left alone so a rollback to the previous
    image still finds it.
    """
    target = _yaml_path()
    if target == DEFAULT_PATH or target.exists() or not DEFAULT_PATH.exists():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(DEFAULT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        logger.info(f"settings migrated {DEFAULT_PATH} → {target}")
    except Exception as e:  # noqa: BLE001 — never block startup
        logger.warning(f"settings migration failed: {e}")


def apply_overlay() -> None:
    """Load settings.yml and copy into os.environ. Call once at startup."""
    _migrate_legacy_file()
    try:
        n = _encrypt_plaintext_secrets()
        if n:
            logger.warning(f"settings secrets encrypted at rest — {n} value(s)")
    except Exception as e:  # noqa: BLE001 — 迁移失败也要能起来（明文照读）
        logger.warning(f"settings secret migration failed: {e}")
    raw = _load_flat()
    applied = 0
    for key, value in raw.items():
        env_var = ENV_MAPPING.get(key)
        if not env_var:
            continue
        if value is None or (isinstance(value, str) and not value.strip()):
            os.environ.pop(env_var, None)
        else:
            os.environ[env_var] = _serialize(value)
        applied += 1
    if applied:
        logger.info(f"settings overlay applied — {applied} keys from {_yaml_path()}")


def _serialize(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def snapshot(mask_sensitive: bool = True) -> dict[str, Any]:
    """Current effective values keyed by the UI's flat keys."""
    out: dict[str, Any] = {}
    for key, env_var in ENV_MAPPING.items():
        v = os.environ.get(env_var, "")
        if mask_sensitive and key in SENSITIVE_KEYS and v:
            # Show "set, N chars" so user knows it exists without leaking content.
            out[key] = f"<set · {len(v)} chars>"
        else:
            out[key] = v
    return out


def save(updates: dict[str, Any]) -> dict[str, Any]:
    """Apply updates to env + persist to settings.yml + reload modules.

    `updates` may use either flat keys (`audit.enabled`) or nested
    (`{audit: {enabled: true}}`); both work.

    Sensitive sentinel values like `<set · N chars>` are ignored — that
    means "leave this key untouched", same UX as the LLM provider editor.
    """
    flat = _flatten(updates) if any(isinstance(v, dict) for v in updates.values()) else updates

    # Validate keys
    unknown = [k for k in flat if k not in ENV_MAPPING]
    if unknown:
        raise ValueError(f"unknown settings keys: {unknown}")

    # Drop sentinels — UI sends the masked placeholder back when user
    # didn't touch the field.
    cleaned: dict[str, Any] = {}
    for k, v in flat.items():
        if isinstance(v, str) and v.startswith("<set ·") and v.endswith("chars>"):
            continue
        cleaned[k] = v

    # URL validation for audit sinks — empty/blank is fine (means "disabled"),
    # but a misformed URL silently broke every audit emit at runtime and
    # spammed the gateway log on each API call.
    _validate_sink_urls(cleaned)
    _validate_masking_mode(cleaned)
    _validate_es_url(cleaned)

    # 先落盘再改 os.environ。反过来的话，盘写失败（卷只读、磁盘满）时进程内已经
    # 生效、盘上没有：界面显示保存成功，重启之后静默回到旧值 —— 对「把网关指到
    # 另一个 ES」这种改动，这是最难查的一类现象。
    on_disk = _flatten(_load_yaml())  # 原样的存储形态：没动过的密文原样带回去
    for key, value in cleaned.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            on_disk.pop(key, None)
        else:
            on_disk[key] = value
    _write_yaml(on_disk)

    for key, value in cleaned.items():
        env_var = ENV_MAPPING[key]
        if value is None or (isinstance(value, str) and not value.strip()):
            os.environ.pop(env_var, None)
        else:
            os.environ[env_var] = _serialize(value)
    logger.info(f"settings saved — {len(cleaned)} key(s) → {_yaml_path()}")

    _reset_dependents()
    return snapshot()


def changed_keys(updates: dict[str, Any]) -> list[str]:
    """Flat setting names an update touches — for audit, without the values."""
    if not isinstance(updates, dict):
        return []
    flat = _flatten(updates) if any(isinstance(v, dict) for v in updates.values()) else updates
    return sorted(flat)


def _validate_masking_mode(cleaned: dict[str, Any]) -> None:
    """Refuse a masking mode that is not one of the three.

    Masking is no longer license-gated (all three modes are free), so this is
    plain input validation now — but it stays at the API boundary rather than
    in current_mode(): an operator setting RST_MASKING_MODE in .env owns their
    box, and second-guessing that at read time would silently change how a
    running deployment masks.
    """
    mode = cleaned.get("masking_mode")
    if not isinstance(mode, str) or not mode.strip():
        return
    from . import field_masking

    mode = mode.strip().lower()
    allowed = field_masking.available_modes()
    if mode not in allowed:
        raise ApiError(
            "masking_mode_unavailable", mode=repr(mode), choices=', '.join(allowed)
        )


_SYSLOG_SCHEMES = ("udp", "tcp", "tls")
_WEBHOOK_SCHEMES = ("http", "https")

# Hosts an audit webhook must never point at. Loopback and link-local are the
# unambiguous SSRF targets — 169.254.169.254 is the cloud instance-metadata
# endpoint on AWS/GCP/Azure/Alibaba. Ordinary private ranges (10/172.16/192.168)
# are NOT blocked: an on-prem SIEM lives there and that is the normal case.
_WEBHOOK_BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "instance-data"}


def _validate_sink_urls(cleaned: dict[str, Any]) -> None:
    """Reject malformed audit sink URLs at save time.

    Blank/missing/None is fine — that means "disable this sink".
    """
    from urllib.parse import urlparse

    syslog = cleaned.get("audit.syslog_url")
    if isinstance(syslog, str) and syslog.strip():
        u = urlparse(syslog.strip())
        if u.scheme not in _SYSLOG_SCHEMES or not u.hostname:
            raise ApiError(
                "syslog_url_invalid", value=repr(syslog), schemes=', '.join(_SYSLOG_SCHEMES)
            )

    webhook = cleaned.get("audit.webhook_url")
    if isinstance(webhook, str) and webhook.strip():
        u = urlparse(webhook.strip())
        if u.scheme not in _WEBHOOK_SCHEMES or not u.hostname:
            raise ApiError("audit_webhook_url_invalid", value=repr(webhook))
        _check_webhook_host(u.hostname)


def _check_webhook_host(host: str) -> None:
    """Constrain where audit events may be POSTed.

    Audit events carry the operator's identity, the indices they touched and
    what they did, and this URL decides who receives them. Two controls:

      RST_AUDIT_WEBHOOK_ALLOWLIST — comma-separated host patterns (fnmatch,
      e.g. `siem.corp.example,*.internal`). Set it and nothing else is
      accepted. This is the real control; use it.

      Otherwise, loopback and link-local are refused. 169.254.169.254 is the
      instance-metadata endpoint on every major cloud, and pointing an
      outbound POST at it is never a SIEM configuration.

    Known limit, stated rather than papered over: a DNS name that resolves into
    blocked space is not caught — the check is on the literal host. Resolving
    here would put a DNS lookup (and its failure modes) inside a settings save.
    The allowlist is what closes that gap.
    """
    import fnmatch
    import ipaddress

    host = host.strip().lower().strip("[]")

    patterns = [p.strip() for p in
                os.environ.get("RST_AUDIT_WEBHOOK_ALLOWLIST", "").split(",") if p.strip()]
    if patterns:
        if not any(fnmatch.fnmatch(host, p.lower()) for p in patterns):
            raise ApiError(
                "audit_webhook_host_not_allowed", host=repr(host), patterns=', '.join(patterns)
            )
        return

    if host in _WEBHOOK_BLOCKED_HOSTS:
        raise ApiError("audit_webhook_host_refused", host=repr(host))
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return  # a name — allowed, see the limit noted above
    if ip.is_loopback or ip.is_link_local:
        raise ApiError("audit_webhook_host_link_local", host=repr(host))


def _validate_es_url(cleaned: dict[str, Any]) -> None:
    """Reject an ES URL that cannot possibly connect.

    Only shape is checked here; reachability is `POST /api/settings/es/test`,
    which the UI is expected to run first. This is the last guard against
    saving something that would take every ES-backed page down — including the
    settings page the admin would need to fix it from.
    """
    from urllib.parse import urlparse

    url = cleaned.get("es.url")
    if url is None or (isinstance(url, str) and not url.strip()):
        return  # blank = fall back to the ES_URL default
    if not isinstance(url, str):
        raise ApiError("es_url_not_string")
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ApiError("es_url_invalid", value=repr(url))


def _reset_dependents() -> None:
    """Force singletons to re-read from os.environ on next access.

    Each reset is isolated so one failing subsystem cannot leave the rest stale,
    but a failure is logged rather than swallowed: silently skipping a reset
    means the admin saves a setting, gets a success response, and the gateway
    keeps enforcing the old value — the whitelist and rate-limit cases are
    security-relevant.
    """

    def _reset_index_whitelist() -> None:
        from . import index_whitelist
        index_whitelist._singleton = None  # type: ignore[attr-defined]

    def _reset_audit() -> None:
        from . import audit
        audit.reset_sinks()

    def _reset_field_masking() -> None:
        from . import field_masking
        if hasattr(field_masking, "reset"):
            field_masking.reset()

    def _reset_backend_adapter() -> None:
        from . import backend_adapter
        backend_adapter.reset()

    def _reset_es_client() -> None:
        # Drop the connection singleton so the next request dials the new host.
        # The old client owns open sockets and closing it is async while this
        # function is sync, so hand the close to the running loop when there is
        # one (the settings API path); without a loop (tests, CLI) the
        # connections die with the process.
        import asyncio

        from . import es_client

        old = es_client.reset_client()
        if old is None:
            return
        try:
            asyncio.get_running_loop().create_task(old.close())
        except RuntimeError:
            pass

    def _reset_rate_limit() -> None:
        from . import rate_limit
        rate_limit.reload()  # re-read RST_RATELIMIT_* — no longer frozen at import

    for name, reset in (
        ("es_client", _reset_es_client),
        ("index_whitelist", _reset_index_whitelist),
        ("audit", _reset_audit),
        ("field_masking", _reset_field_masking),
        ("backend_adapter", _reset_backend_adapter),
        ("rate_limit", _reset_rate_limit),
    ):
        try:
            reset()
        except Exception:  # noqa: BLE001 — one bad subsystem must not block the rest
            logger.exception("settings_reset_failed", extra={"subsystem": name})
