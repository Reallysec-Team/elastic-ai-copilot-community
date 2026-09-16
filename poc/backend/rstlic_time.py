"""Trusted time + clock-rollback detection for the RST License SDK (SEC-TM-1).

``LicenseVerifier.check_expiry`` trusts the local system clock. For an
ONLINE product that's fine — the server's clock is authoritative and the
heartbeat loop re-validates. But an OFFLINE / air-gapped license
(``validate_offline``) has no heartbeat, so an attacker can roll the local
clock BACK to sit inside the validity window (or inside an expired license's
grace) indefinitely.

This module closes that two ways, mirroring the approach proven in eoovoi:

* **Trusted time** — fetch the current time from a TLS-authenticated HTTPS
  ``Date`` header (falling back to NTP), cached briefly in the SDK's storage.
  Unlike the local clock (or plaintext NTP) a network attacker can't forge it
  without also forging a trusted certificate. Use the product's OWN
  license-server URL as the source for the strongest guarantee.
* **Rollback detection** — persist the furthest-forward time ever seen and
  refuse (or warn) when the clock now reads meaningfully earlier. This works
  with NO network at all, so it protects a truly air-gapped install where a
  trusted time source is unreachable — which is exactly the rollback vector.

Self-contained (stdlib only) and exception-light: rollback checks return bools
so the caller (the verifier) owns the LicenseError. ``trusted_now`` raises the
local :class:`TrustedTimeUnavailable` only in ``strict`` mode.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import socket
import struct
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

# RSA-PSS verify for signed time (SEC-TM-1 strong source). Vendor-fallback like
# the rest of the SDK so it works on bare Splunk 9.x runtimes.
try:
    from cryptography.exceptions import InvalidSignature as _InvalidSignature
    from cryptography.hazmat.primitives import hashes as _hashes, serialization as _serialization
    from cryptography.hazmat.primitives.asymmetric import padding as _padding
except ImportError:  # pragma: no cover
    import sys as _sys
    _vd = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendor')
    if _vd not in _sys.path:
        _sys.path.insert(0, _vd)
    from cryptography.exceptions import InvalidSignature as _InvalidSignature
    from cryptography.hazmat.primitives import hashes as _hashes, serialization as _serialization
    from cryptography.hazmat.primitives.asymmetric import padding as _padding

logger = logging.getLogger('rstlic_time')

# Domain-prefixed message the license-server signs for /v1/time (must match
# server signing.sign_time). Disjoint from license-token + endorsement signing.
_TIME_DOMAIN = b'rstlic-time-v1\x00'

# Storage keys (namespaced so they don't collide with token / CRL state).
_TIME_CACHE_KEY = 'rstlic_time_cache'
_LASTSEEN_PREFIX = 'rstlic_lastseen_'

#: A fetched trusted time is cached this long (seconds): a hot validation path
#: hits the network at most once per window instead of on every call.
_DEFAULT_TTL = 3600


class TrustedTimeUnavailable(Exception):
    """No trusted time source could be reached while operating in strict mode."""


# ---------------------------------------------------------------------------
# Source overrides (env) — closed networks point these at internal sources.
# ---------------------------------------------------------------------------
def _https_servers(explicit: Optional[Iterable[str]]) -> tuple[str, ...]:
    if explicit:
        return tuple(explicit)
    env = os.environ.get('RSTLIC_TIME_URL')
    if env:
        urls = tuple(u.strip() for u in env.split(',') if u.strip())
        if urls:
            return urls
    return ('https://www.cloudflare.com', 'https://www.google.com')


def _ntp_servers(explicit: Optional[Iterable[str]]) -> tuple[str, ...]:
    if explicit:
        return tuple(explicit)
    env = os.environ.get('RSTLIC_NTP')
    if env:
        servers = tuple(s.strip() for s in env.split(',') if s.strip())
        if servers:
            return servers
    return ('pool.ntp.org', 'time.cloudflare.com')


# ---------------------------------------------------------------------------
# Time fetchers
# ---------------------------------------------------------------------------
def _https_time(urls: Iterable[str], timeout: float) -> Optional[float]:
    """Current UNIX time from a TLS-authenticated HTTPS ``Date`` header, or None.

    The response travels over a certificate-validated TLS connection, so a
    network attacker cannot forge the time without a trusted cert for the host.
    """
    import email.utils as eut
    import ssl
    import urllib.request as urlreq

    ctx = ssl.create_default_context()
    for url in urls:
        try:
            request = urlreq.Request(url, method='HEAD')
            with urlreq.urlopen(request, timeout=timeout, context=ctx) as response:
                date = response.headers.get('Date')
            if date:
                value = eut.parsedate_to_datetime(date)
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                return value.timestamp()
        except Exception:  # noqa: BLE001 — try the next source
            continue
    return None


def _ntp_time(servers: Iterable[str], timeout: float) -> Optional[float]:
    """Current UNIX time from a plaintext NTP server, or None. Weaker than the
    HTTPS source (forgeable on a hostile network) — used only as a fallback."""
    packet = b'\x1b' + 47 * b'\0'
    for server in servers:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(packet, (server, 123))
            data, _ = sock.recvfrom(48)
            if len(data) >= 48:
                seconds = struct.unpack('!12I', data[:48])[10]
                return seconds - 2208988800
        except Exception:  # noqa: BLE001
            continue
        finally:
            sock.close()
    return None


def trusted_time(*, time_urls: Optional[Iterable[str]] = None,
                 ntp_servers: Optional[Iterable[str]] = None,
                 timeout: float = 5.0) -> Optional[float]:
    """A trusted UNIX time: prefer the authenticated HTTPS source, fall back to
    NTP. Returns None if neither is reachable. (Patched in tests.)"""
    stamp = _https_time(_https_servers(time_urls), timeout)
    if stamp is not None:
        return stamp
    return _ntp_time(_ntp_servers(ntp_servers), min(timeout, 2.0))


def signed_time(url: str, public_pems: Iterable[Any], *,
                timeout: float = 5.0) -> Optional[float]:
    """Current UNIX time from the license-server's ``GET /v1/time/<app>`` —
    an ``{ts, sig}`` response whose ``sig`` is RSA-PSS over the timestamp by the
    app's SIGNING key. Verified here with the SAME trusted public key(s) that
    validate licenses, so — unlike a plain HTTPS ``Date`` header — an attacker
    cannot forge it even with a valid TLS cert for some other domain (e.g. via a
    spoofed ``RSTLIC_TIME_URL``). Returns None on any failure.
    """
    import ssl
    import urllib.request as urlreq

    pems = [p if isinstance(p, bytes) else p.encode('utf-8') for p in public_pems if p]
    if not pems:
        return None
    ctx = ssl.create_default_context()
    try:
        with urlreq.urlopen(url, timeout=timeout, context=ctx) as response:
            data = json.loads(response.read().decode('utf-8'))
        ts = str(data['ts'])
        sig = base64.b64decode(data['sig'])
    except Exception:  # noqa: BLE001
        return None
    message = _TIME_DOMAIN + ts.encode('utf-8')
    for pem in pems:
        try:
            pub = _serialization.load_pem_public_key(pem)
        except Exception:  # noqa: BLE001
            continue
        try:
            pub.verify(
                sig, message,
                _padding.PSS(mgf=_padding.MGF1(_hashes.SHA256()),
                             salt_length=_padding.PSS.AUTO),
                _hashes.SHA256(),
            )
            return _parse_iso(ts).timestamp()
        except _InvalidSignature:
            continue
        except Exception:  # noqa: BLE001 — malformed ts etc.
            return None
    return None


# ---------------------------------------------------------------------------
# trusted_now — cached, returns (datetime, trusted?)
# ---------------------------------------------------------------------------
def _storage_get(storage: Any, key: str) -> str:
    if storage is None:
        return ''
    try:
        return storage.get(key) or ''
    except Exception:  # noqa: BLE001
        return ''


def _storage_set(storage: Any, key: str, value: str) -> None:
    if storage is None:
        return
    try:
        storage.set(key, value)
    except Exception:  # noqa: BLE001
        pass


def trusted_now(storage: Any = None, *,
                time_urls: Optional[Iterable[str]] = None,
                ntp_servers: Optional[Iterable[str]] = None,
                ttl: int = _DEFAULT_TTL,
                strict: bool = False,
                verified_fetcher: Optional[Any] = None) -> tuple[datetime, bool]:
    """Return ``(utc_datetime, trusted)``.

    A trusted time is fetched from the strongest available source — a
    ``verified_fetcher`` (signed time, returning unix-or-None) if given, else an
    authenticated HTTPS source (NTP fallback) — and cached in ``storage`` for
    ``ttl`` seconds. Within the window the cached value is advanced by the
    locally-elapsed time (so a repeatedly-run check hits the network at most
    once per window). When no trusted source is reachable: ``strict`` raises
    :class:`TrustedTimeUnavailable`; otherwise the local clock is returned with
    ``trusted=False`` (the caller then leans on rollback detection).
    """
    local = datetime.now(timezone.utc)
    local_unix = local.timestamp()

    raw = _storage_get(storage, _TIME_CACHE_KEY)
    if raw:
        try:
            cache = json.loads(raw)
            age = local_unix - float(cache['at'])
            if 0 <= age < ttl:
                approx = float(cache['unix']) + age
                return datetime.fromtimestamp(approx, timezone.utc), True
        except (ValueError, KeyError, TypeError):
            pass

    stamp = None
    if verified_fetcher is not None:
        try:
            stamp = verified_fetcher()
        except Exception:  # noqa: BLE001 — fall back to HTTPS/NTP
            stamp = None
    if stamp is None:
        stamp = trusted_time(time_urls=time_urls, ntp_servers=ntp_servers)
    if stamp is not None:
        _storage_set(storage, _TIME_CACHE_KEY,
                     json.dumps({'unix': stamp, 'at': local_unix}))
        return datetime.fromtimestamp(stamp, timezone.utc), True

    if strict:
        raise TrustedTimeUnavailable(
            'no trusted time source (HTTPS/NTP) reachable in strict mode')
    return local, False


# ---------------------------------------------------------------------------
# Rollback detection (offline-capable: storage only, no network)
# ---------------------------------------------------------------------------
def _parse_iso(s: str) -> datetime:
    s = s.strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def lastseen_key(license_id: Optional[str]) -> str:
    return _LASTSEEN_PREFIX + str(license_id or 'default')


def check_rollback(storage: Any, key: str, now: datetime, *,
                   skew: timedelta = timedelta(days=1)) -> bool:
    """True if ``now`` is earlier than the furthest-forward time ever recorded
    under ``key`` by more than ``skew`` — i.e. the clock was rolled back. Does
    NOT update storage (call :func:`record_seen` for that). A missing / corrupt
    last-seen is treated as "no rollback" (first run)."""
    raw = _storage_get(storage, key)
    if not raw:
        return False
    try:
        last_seen = _parse_iso(raw)
    except (ValueError, TypeError):
        return False
    return now < (last_seen - skew)


def record_seen(storage: Any, key: str, now: datetime) -> None:
    """Advance the recorded last-seen time to ``now`` — but only FORWARD, so a
    rolled-back clock can never lower the high-water mark."""
    raw = _storage_get(storage, key)
    if raw:
        try:
            if _parse_iso(raw) >= now:
                return  # never move the high-water mark backwards
        except (ValueError, TypeError):
            pass
    _storage_set(storage, key, now.isoformat())
