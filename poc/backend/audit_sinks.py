"""Optional fan-out sinks for the audit pipeline.

The Elasticsearch write inside ``audit.write_event`` is the canonical, always-on
audit destination. These sinks are *additional* delivery targets (syslog,
generic webhook) that customers may opt into via env vars. Each sink is:

  * **best-effort** — a sink that fails MUST NOT raise into the caller. The
    failure is logged at WARN as ``audit_sink_failed`` and swallowed.
  * **isolated** — one sink failing does not affect the others. ``audit.py``
    dispatches with ``asyncio.gather(..., return_exceptions=True)``.
  * **stateless per write** — connections (TCP syslog, HTTP clients) are opened
    and closed per event. Audit volume is low; this avoids stale-socket bugs in
    long-lived gateway processes and keeps the failure blast radius small.

Configuration (all env vars are optional; missing ones simply skip that sink):

    RST_AUDIT_SYSLOG_URL        e.g. udp://syslog.acme.local:514
                                or   tcp://syslog.acme.local:601
                                or   tls://syslog.acme.local:6514  (TLS-encrypted)
                                RST_AUDIT_TLS_VERIFY=false also relaxes the
                                tls:// syslog certificate check.
    RST_AUDIT_WEBHOOK_URL       Generic POST target
    RST_AUDIT_WEBHOOK_HEADERS   Optional. "Header1:Value1;Header2:Value2"
    RST_AUDIT_TLS_VERIFY        "false" disables TLS verification on the
                                webhook sink. Default true.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("rst.audit.sinks")

# webhook 转发的有界重试。三次、秒级 —— 目标是盖掉网络抖动，不是撑过对端
# 长时间宕机（那种情况由记录本体上的 forward_failed 标记兵底，事后重放）。
_WEBHOOK_ATTEMPTS = 3
_WEBHOOK_BACKOFF_S = (0.5, 1.5)

# Severity mapping per RFC 5424 (numeric severity codes).
_SEVERITY_MAP = {
    "info": 6,
    "informational": 6,
    "notice": 5,
    "warning": 4,
    "warn": 4,
    "error": 3,
    "err": 3,
    "critical": 2,
    "crit": 2,
}
# facility local0 == 16; PRI = facility * 8 + severity.
_FACILITY_LOCAL0 = 16
_DEFAULT_SEVERITY = 6  # info


def _tls_verify_default() -> bool:
    """RST_AUDIT_TLS_VERIFY=false disables verification on HTTP sinks."""
    raw = os.environ.get("RST_AUDIT_TLS_VERIFY")
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no")


class Sink(ABC):
    """Abstract audit sink. Implementations must never raise from ``write``.

    `write` 返回「送到了没有」。以前返回 None，失败只进日志 —— 于是调用方
    没有任何办法知道转发掉了，事后也无从查「哪些没转出去」。
    实现仍然不得抛异常：转发失败不能影响记录本体的写入。
    """

    #: Short label used in failure logs so operators can identify the sink.
    kind: str = "sink"

    @abstractmethod
    async def write(self, event: dict[str, Any]) -> bool:  # pragma: no cover
        ...

    def _log_failure(self, exc: BaseException) -> None:
        # Truncate the error excerpt — sinks that return HTML error pages can
        # otherwise dump kilobytes into the gateway log.
        excerpt = str(exc)
        if len(excerpt) > 400:
            excerpt = excerpt[:400] + "..."
        logger.warning(
            "audit_sink_failed",
            extra={"sink": self.kind, "error": excerpt},
        )


# --------------------------------------------------------------------------- #
# Syslog (RFC 5424)
# --------------------------------------------------------------------------- #


class SyslogSink(Sink):
    """RFC 5424 syslog sink.

    Accepts ``udp://host:port`` or ``tcp://host:port``. UDP uses a one-shot
    ``SOCK_DGRAM`` socket. TCP uses ``asyncio.open_connection`` and closes the
    writer after each event — audit traffic is low-volume and per-event
    reconnection avoids half-open sockets after firewall idle-timeouts.
    """

    kind = "syslog"
    HOSTNAME = socket.gethostname() or "-"
    APP_NAME = "rst-copilot"

    def __init__(self, url: str) -> None:
        self.url = url
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("udp", "tcp", "tls"):
            raise ValueError(
                f"SyslogSink: unsupported scheme {scheme!r} "
                "(expected udp://, tcp:// or tls://)"
            )
        if not parsed.hostname:
            raise ValueError(f"SyslogSink: missing host in {url!r}")
        self.scheme = scheme
        self.host = parsed.hostname
        self.port = parsed.port or (514 if scheme == "udp" else 6514)

    @staticmethod
    def _severity_for(event: dict[str, Any]) -> int:
        sev = event.get("severity")
        if isinstance(sev, str):
            return _SEVERITY_MAP.get(sev.strip().lower(), _DEFAULT_SEVERITY)
        if isinstance(sev, int) and 0 <= sev <= 7:
            return sev
        return _DEFAULT_SEVERITY

    @staticmethod
    def _rfc5424_timestamp() -> str:
        # RFC 5424 wants RFC3339 with millisecond precision and a Z/offset.
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    def _format(self, event: dict[str, Any]) -> bytes:
        severity = self._severity_for(event)
        pri = _FACILITY_LOCAL0 * 8 + severity
        ts = self._rfc5424_timestamp()
        # HEADER: <PRI>VERSION TIMESTAMP HOSTNAME APP-NAME PROCID MSGID
        # STRUCTURED-DATA: "-" (none)
        # MSG: BOM + JSON payload (BOM signals UTF-8 per RFC 5424).
        try:
            payload = json.dumps(event, default=str, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            payload = json.dumps({"audit_serialize_error": True})
        msg = (
            f"<{pri}>1 {ts} {self.HOSTNAME} {self.APP_NAME} - - - "
            "﻿" + payload
        )
        line = msg.encode("utf-8", errors="replace")
        # TCP syslog (RFC 6587) commonly uses octet-counting; non-transparent
        # framing (LF-terminated) is widely accepted and simpler. We use LF.
        if self.scheme in ("tcp", "tls"):
            line = line + b"\n"
        return line

    async def write(self, event: dict[str, Any]) -> bool:
        try:
            data = self._format(event)
            if self.scheme == "udp":
                # Run the blocking sendto in a thread so we never stall the
                # event loop on DNS or routing hiccups.
                await asyncio.to_thread(self._send_udp, data)
            else:
                await self._send_tcp(data)
        except Exception as e:  # noqa: BLE001
            self._log_failure(e)
            return False
        # UDP 是单向的，发出去不代表对端收到 —— 这里的 True 只能说「本地没出错」。
        # syslog 本来就没有交付确认，不要假装有。
        return True

    def _send_udp(self, data: bytes) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(2.0)
            sock.sendto(data, (self.host, self.port))
        finally:
            sock.close()

    async def _send_tcp(self, data: bytes) -> None:
        # Open + close per write. Audit is low-volume; this dodges stale-socket
        # bugs after firewall idle-timeouts and keeps reconnect logic trivial.
        ssl_ctx = None
        if self.scheme == "tls":
            import ssl
            ssl_ctx = ssl.create_default_context()
            if not _tls_verify_default():
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port, ssl=ssl_ctx), timeout=5.0
        )
        try:
            writer.write(data)
            await asyncio.wait_for(writer.drain(), timeout=5.0)
        finally:
            try:
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
            except Exception:  # noqa: BLE001
                # Best effort: never fail a write because of a noisy close.
                pass


# --------------------------------------------------------------------------- #
# Generic webhook
# --------------------------------------------------------------------------- #


class WebhookSink(Sink):
    """Generic JSON webhook sink. POSTs the event body verbatim."""

    kind = "webhook"

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        verify_tls: bool = True,
    ) -> None:
        if not url:
            raise ValueError("WebhookSink: url is required")
        self.url = url
        self.headers = dict(headers or {})
        self.verify_tls = verify_tls

    async def write(self, event: dict[str, Any]) -> bool:
        """POST 一次，失败就退避重试。

        重试只针对**暂时性**失败：网络错误、5xx、429。其余 4xx 是配置错
        （地址写错、鉴权头不对），重试只是把同一个错误多发两遍。

        这里可以放心 sleep：`write_event` 是 `fire_and_forget` 调度的，不在
        请求路径上。
        """
        send_headers = {"Content-Type": "application/json", **self.headers}
        last: BaseException | None = None
        for attempt in range(_WEBHOOK_ATTEMPTS):
            try:
                async with httpx.AsyncClient(
                    timeout=5.0, verify=self.verify_tls
                ) as client:
                    resp = await client.post(self.url, json=event, headers=send_headers)
                if resp.status_code < 400:
                    return True
                err = RuntimeError(f"Webhook HTTP {resp.status_code}: {resp.text[:200]}")
                if not (resp.status_code >= 500 or resp.status_code == 429):
                    self._log_failure(err)
                    return False
                last = err
            except Exception as e:  # noqa: BLE001
                last = e
            if attempt < _WEBHOOK_ATTEMPTS - 1:
                await asyncio.sleep(_WEBHOOK_BACKOFF_S[attempt])
        if last is not None:
            self._log_failure(last)
        return False


# --------------------------------------------------------------------------- #
# Env loader
# --------------------------------------------------------------------------- #


def _parse_header_pairs(raw: str | None) -> dict[str, str]:
    """Parse "K1:V1;K2:V2" into a dict. Empty / malformed entries are skipped.

    Whitespace around keys/values is stripped. Values may legitimately contain
    ':' (e.g. "Authorization: Bearer abc"), so we only split on the first ':'.
    """
    out: dict[str, str] = {}
    if not raw:
        return out
    for chunk in raw.split(";"):
        if ":" not in chunk:
            continue
        k, _, v = chunk.partition(":")
        k = k.strip()
        v = v.strip()
        if k:
            out[k] = v
    return out


def load_sinks_from_env() -> list[Sink]:
    """Build the configured sink list from environment variables.

    Returns an empty list when nothing is configured. Construction errors for
    any individual sink are logged at WARN and the sink is dropped — we never
    let a malformed env var crash the gateway.
    """
    sinks: list[Sink] = []
    verify_tls = _tls_verify_default()

    syslog_url = (os.environ.get("RST_AUDIT_SYSLOG_URL") or "").strip()
    if syslog_url:
        try:
            sinks.append(SyslogSink(syslog_url))
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "audit_sink_failed",
                extra={"sink": "syslog", "error": f"init: {e}"},
            )

    webhook_url = (os.environ.get("RST_AUDIT_WEBHOOK_URL") or "").strip()
    if webhook_url:
        try:
            headers = _parse_header_pairs(os.environ.get("RST_AUDIT_WEBHOOK_HEADERS"))
            sinks.append(WebhookSink(webhook_url, headers=headers, verify_tls=verify_tls))
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "audit_sink_failed",
                extra={"sink": "webhook", "error": f"init: {e}"},
            )

    return sinks
