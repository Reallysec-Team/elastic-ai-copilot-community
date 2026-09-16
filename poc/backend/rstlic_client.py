"""rstlic_client — pure-Python SDK that any RST Splunk app drops in to talk
to the RST License Server.

Drop this file into <your_app>/bin/lib/ and import it. It depends only on
``requests`` (already vendored by every Splunk app via the appserver layer)
and the existing license_verifier in your app.

Usage from a handler::

    from rstlic_client import RSTLicClient

    client = RSTLicClient(
        license_server_url='https://license.reallysec.com',
        app_id='ai-query-assistant-for-splunk',
        app_version='2.2.10',
        splunk_server_guid=server_guid,
    )

    # Phone home on first successful local verification.
    client.activate(license_id='LIC-...', host_fingerprint=fp)

    # Daily heartbeat (driven by a Splunk modular input or scheduled saved
    # search). The heartbeat is HMAC-signed (SEC-HB-1 fix) using the
    # session_secret returned at activate time.
    new_token = client.heartbeat(license_id='LIC-...', metrics={'queries_today': 12})

Failure semantics (deliberately permissive — a license server outage must
NOT lock customers out instantly):

  * activate(): 4xx from the server means the license is genuinely
    rejected — raise. 5xx / network error → log + return None and let the
    splunk app continue with the offline-verified payload.

  * heartbeat(): same. The splunk app keeps using the cached token; if the
    cache is older than ``offline_grace_days``, it falls back to read-only
    mode (caller's responsibility to enforce that).

Hardware fingerprint sources (SEC-FP-1, recipe **v2** since SDK 1.1.0):

  * machine-id — the sole identity root when readable:
      - Linux:    /etc/machine-id  ||  /sys/class/dmi/id/product_uuid
      - macOS:    ioreg -rd1 -c IOPlatformExpertDevice → IOPlatformUUID
      - Windows:  registry MachineGuid  ||  wmic csproduct get uuid
  * primary MAC — **fallback only**, used when machine-id is unreadable
    (e.g. a container without /etc/machine-id). ``uuid.getnode()`` tracks
    the host's *NIC set*, so it drifts the moment a user starts Docker
    Desktop / WSL / VMware / VirtualBox / Tailscale or unplugs a dock.
    Recipe v1 folded it in unconditionally and bricked those hosts.
  * CPU descriptor (platform.processor() + arch) and OS family — stable
    tie-breakers, always folded in. Volatile vCPU count and kernel release
    are deliberately excluded.

If none of the platform sources yield a usable hardware identifier the
SDK raises :class:`RSTLicHardwareUnavailable` rather than silently
falling back to a public-input hash. This makes piracy attacks (license
copy to a sibling host) detectable; the previous derivation hashed only
public values (server_guid + app_id) and so was reproducible by anyone
holding the SDK.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import platform
import re
import subprocess
import time
import uuid
from typing import Any, Optional

try:
    import requests
except ImportError:
    requests = None  # we'll fall back to urllib for splunk envs without requests

# Use a fixed logger name (not __name__) so callers — including Splunk
# apps that import this file under a different qualified path — always
# see the same logger identity. Tests rely on this when asserting that
# the SEC-FP-1 hard-fail path emits an ERROR record.
logger = logging.getLogger('rstlic_client')

DEFAULT_TIMEOUT_SECONDS = 8


class RSTLicError(Exception):
    """Base class for SDK errors."""


class RSTLicRevoked(RSTLicError):
    """Server reports the license is revoked. Caller should switch to read-only."""


class RSTLicRejected(RSTLicError):
    """Server returned a 4xx — license id mismatch, expired, max_nodes hit, etc."""


class RSTLicUnavailable(RSTLicError):
    """Server returned 5xx, timed out, or network failed. Treat as transient."""


class RSTLicHardwareUnavailable(RSTLicError):
    """No hardware identifier could be read on this host.

    Raised by :func:`fingerprint` when every platform-specific source fails.
    Hard failure is intentional — callers MUST surface this to the user
    (typically by refusing activation) rather than fall back to a
    public-input hash. See SEC-FP-1.
    """


# ---------------------------------------------------------------------------
# Hardware-rooted fingerprint helpers (SEC-FP-1)
#
# Each helper returns a non-empty string if it could read a real hardware
# identifier on this OS, else None / ''. We blend several sources before
# hashing so that a single tampered file (e.g. a forged /etc/machine-id)
# isn't enough on its own to mint a colliding fingerprint.
# ---------------------------------------------------------------------------
def _read_first(*paths: str) -> str:
    """Return the first non-empty file content from ``paths`` (stripped)."""
    for p in paths:
        try:
            with open(p, 'r', encoding='utf-8') as f:
                v = (f.read() or '').strip()
            if v:
                return v
        except (OSError, IOError):
            continue
    return ''


def _run_capture(cmd: list[str], timeout: int = 4) -> str:
    """Run ``cmd`` and return stdout text. Empty string on any failure.

    Subprocess is wrapped tightly because some Splunk hosts ship
    locked-down PATHs / strange shells; we never want a child-process
    error to propagate up and crash the SDK at fingerprint time.
    """
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL,
                                      timeout=timeout)
        return out.decode('utf-8', errors='replace').strip()
    except (FileNotFoundError, subprocess.SubprocessError,
            subprocess.TimeoutExpired, OSError, ValueError):
        return ''


def _linux_machine_id() -> str:
    # /etc/machine-id (systemd) — 32 hex chars, set at first boot, stable.
    # /sys/class/dmi/id/product_uuid — DMI uuid, root-readable; falls back
    # to /sys/devices/virtual/dmi/id/product_uuid on some kernels.
    return _read_first(
        '/etc/machine-id',
        '/var/lib/dbus/machine-id',
        '/sys/class/dmi/id/product_uuid',
        '/sys/devices/virtual/dmi/id/product_uuid',
    )


def _macos_machine_id() -> str:
    out = _run_capture(['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'])
    if not out:
        return ''
    m = re.search(r'"IOPlatformUUID"\s*=\s*"([0-9A-Fa-f-]+)"', out)
    if m:
        return m.group(1)
    # Fallback: serial number (ioreg same query)
    m = re.search(r'"IOPlatformSerialNumber"\s*=\s*"([^"]+)"', out)
    if m:
        return m.group(1)
    return ''


def _windows_machine_id() -> str:
    # Preferred: HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Cryptography\MachineGuid
    try:
        import winreg  # type: ignore
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r'SOFTWARE\Microsoft\Cryptography',
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ) as key:
                v, _ = winreg.QueryValueEx(key, 'MachineGuid')
                if v:
                    return str(v).strip()
        except OSError:
            pass
    except ImportError:
        pass
    # Fallback: wmic csproduct get uuid (deprecated in Win11 but still common
    # on Splunk-bundled Server hosts)
    out = _run_capture(['wmic', 'csproduct', 'get', 'uuid'])
    if out:
        for line in out.splitlines():
            v = line.strip()
            if v and v.upper() != 'UUID':
                return v
    # Last-ditch: powershell Get-CimInstance
    out = _run_capture([
        'powershell', '-NoProfile', '-Command',
        '(Get-CimInstance Win32_ComputerSystemProduct).UUID',
    ])
    return out


def _platform_machine_id() -> str:
    sysname = platform.system().lower()
    if sysname == 'linux':
        return _linux_machine_id()
    if sysname == 'darwin':
        return _macos_machine_id()
    if sysname == 'windows':
        return _windows_machine_id()
    # Unknown OS (BSD / Solaris / containerised exotic) — try the linux
    # paths anyway since systemd is widespread.
    return _linux_machine_id()


def _primary_mac() -> str:
    """Return the host's primary MAC address (12 lowercase hex chars).

    ``uuid.getnode()`` returns a 48-bit int. Per its docs, when it cannot
    discover a real interface it sets bit 40 (the multicast bit) and
    returns a random address — we treat that as 'no MAC' so a randomly-
    generated value never enters the fingerprint.
    """
    node = uuid.getnode()
    # Multicast bit (LSB of first byte) set → random fallback.
    first_byte = (node >> 40) & 0xFF
    if first_byte & 0x01:
        return ''
    return f'{node:012x}'


def _cpu_descriptor() -> str:
    """Combine platform.processor() + arch into one string.

    Not unique on its own (whole datacenters of the same SKU collide) but useful
    as a tie-breaker on top of machine-id / MAC.

    Fingerprint-stability fix: os.cpu_count() was removed from this descriptor.
    vCPU count changes on a routine VM resize, which would silently alter the
    host fingerprint and invalidate an already-bound activation (session /
    bound_fingerprint mismatch -> license lockout). The stable hardware roots
    (machine-id / MAC) carry the uniqueness; a volatile vCPU count is not worth
    a license-bricking regression.
    """
    proc = (platform.processor() or '').strip()
    machine = (platform.machine() or '').strip()
    return f'{proc}|{machine}'


# ---------------------------------------------------------------------------
# Heartbeat HMAC helper (SEC-HB-1)
# ---------------------------------------------------------------------------
def _hmac_heartbeat(session_secret: str, body_json: bytes,
                    timestamp: str) -> str:
    """Compute the heartbeat HMAC. Algorithm: HMAC-SHA256 over
    ``body_json + str(timestamp)`` with key = session_secret.
    Returns lowercase hex (64 chars)."""
    key = session_secret.encode('utf-8')
    msg = body_json + timestamp.encode('utf-8')
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


class RSTLicClient:
    """Pure-data client; no Splunk-specific imports inside."""

    def __init__(self, *,
                 license_server_url: str,
                 app_id: str,
                 app_version: str,
                 splunk_server_guid: Optional[str] = None,
                 server_guid: Optional[str] = None,
                 timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        # ``server_guid`` is the platform-neutral name; ``splunk_server_guid``
        # is the original Splunk-flavoured kwarg, kept so existing Splunk
        # callers keep working unchanged. Either is accepted; for non-Splunk
        # products it's just a stable per-host identifier (advisory only —
        # identity binding is enforced server-side via host_fingerprint).
        guid = server_guid if server_guid is not None else splunk_server_guid
        if guid is None:
            raise TypeError('RSTLicClient requires server_guid (or splunk_server_guid)')
        self._base = license_server_url.rstrip('/')
        self._app_id = app_id
        self._app_version = app_version
        self._guid = guid
        self._timeout = timeout_seconds

    # Read-only accessors so the lifecycle layer doesn't reach into privates.
    @property
    def app_id(self) -> str:
        return self._app_id

    @property
    def app_version(self) -> str:
        return self._app_version

    @property
    def server_guid(self) -> str:
        return self._guid

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------
    def activate(self, *, license_id: str, host_fingerprint: str,
                 splunk_version: Optional[str] = None) -> dict[str, Any]:
        body = {
            'license_id':       license_id,
            'app_id':           self._app_id,
            'server_guid':      self._guid,
            'host_fingerprint': host_fingerprint,
            'splunk_version':   splunk_version or '',
            'app_version':      self._app_version,
        }
        return self._post_json('/v1/activate', body)

    def heartbeat(self, *, license_id: str,
                  host_fingerprint: str,
                  session_secret: str,
                  metrics: Optional[dict[str, Any]] = None,
                  content_sha: Optional[str] = None) -> dict[str, Any]:
        """Send an HMAC-signed heartbeat (SEC-HB-1).

        ``session_secret`` is the plaintext secret returned by
        :meth:`activate` — the SDK persists it in storage/passwords on the
        Splunk side so it survives splunkd restarts. Without a valid
        ``session_secret`` the server replies 401.

        ``app_version`` (from the client) is always sent so the server can
        apply the P1.5 downgrade gate. ``content_sha`` is the sha256 of the
        content pack the client currently holds; when it matches the server's
        stored pack the response omits the (KB-sized) pack, otherwise the
        server inlines a fresh one under ``content_pack`` (P1 online update).
        """
        body = {
            'license_id':       license_id,
            'app_id':           self._app_id,
            'server_guid':      self._guid,
            'host_fingerprint': host_fingerprint,
            'app_version':      self._app_version,
            'metrics':          metrics or {},
        }
        if content_sha:
            body['content_sha'] = content_sha
        # Server-side replay protection requires a stable JSON encoding;
        # we do the encoding once here, sign it, and reuse the same bytes
        # for the request body. ``sort_keys`` keeps the digest stable
        # under hash-randomisation and across Python versions.
        payload = json.dumps(body, separators=(',', ':'),
                             sort_keys=True).encode('utf-8')
        ts = str(int(time.time()))
        sig = _hmac_heartbeat(session_secret, payload, ts)
        headers = {
            'X-Heartbeat-HMAC': sig,
            'X-Timestamp':      ts,
        }
        return self._post_json('/v1/heartbeat', body,
                               extra_headers=headers,
                               raw_payload=payload)

    def refresh_session(self, *, license_id: str,
                        host_fingerprint: str) -> dict[str, Any]:
        """Mint a fresh session_token (SEC-AC-1) when the previous one is
        about to expire. Server validates that the supplied license is
        still active and that ``host_fingerprint`` matches the original
        activation row — i.e. the same machine that activated.
        """
        body = {
            'license_id':       license_id,
            'app_id':           self._app_id,
            'host_fingerprint': host_fingerprint,
        }
        return self._post_json('/v1/refresh-session', body)

    @staticmethod
    def fingerprint(server_guid: str = '', app_id: str = '',
                    salt: str = '') -> str:
        """Hardware-rooted fingerprint, recipe **v2** (SEC-FP-1, SDK 1.1.0+).

        Returns a 64-char lowercase hex sha256 over:
          * platform machine-id (Linux /etc/machine-id, macOS IOPlatformUUID,
            Windows registry MachineGuid) — the identity root
          * primary MAC — **only when machine-id is unreadable**. When
            machine-id is present the MAC slot is empty and contributes no
            entropy, because ``uuid.getnode()`` follows the host's NIC set:
            starting Docker Desktop / WSL / a VPN, or unplugging a dock,
            changes it and would silently invalidate the activation.
          * CPU descriptor (``platform.processor()`` + arch; volatile vCPU
            count / kernel release excluded for fingerprint stability)
          * OS family (``platform.system()`` — kernel release excluded)
          * The public ``server_guid`` + ``app_id`` + ``salt``, folded in
            ONLY as a salt — they carry none of the entropy, so the old
            "anyone with the SDK can derive any host's fingerprint" attack
            still does not work.

        Dropping the MAC does not weaken the binding: machine-id is already
        unique and secret-enough per host, and what we removed is a *volatile*
        input, not a *confidential* one.

        Raises :class:`RSTLicHardwareUnavailable` if **every** hardware
        source fails (containers without machine-id and without a real
        MAC). The previous fallback to ``sha256(server_guid + app_id)``
        was the very thing this rewrite removes — silent fallback is a
        regression we explicitly refuse to ship.
        """
        machine_id = _platform_machine_id()
        # Only pay for (and only trust) the MAC when there is no machine-id.
        mac = '' if machine_id else _primary_mac()

        # Hard fail when nothing useful is readable — cpu alone is not unique
        # enough to count as hardware.
        if not machine_id and not mac:
            logger.error(
                'rstlic fingerprint: no hardware identifier available '
                '(machine-id / MAC both empty); refusing to emit a '
                'guessable public-input fingerprint. See SEC-FP-1.'
            )
            raise RSTLicHardwareUnavailable(
                'no hardware identifier (machine-id or MAC) available; '
                'this host cannot be uniquely fingerprinted'
            )

        h = hashlib.sha256()
        # NUL-separated so individual components can't ambiguously concatenate
        # into another component. platform.release() (kernel version) is
        # deliberately excluded: it changes on a routine kernel upgrade +
        # reboot, which would alter the fingerprint and invalidate an
        # already-bound activation.
        for part in (machine_id, mac, _cpu_descriptor(), platform.system(),
                     server_guid, app_id, salt):
            h.update((part or '').encode('utf-8', errors='replace'))
            h.update(b'\0')
        return h.hexdigest()

    # -----------------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------------
    def _post_json(self, path: str, body: dict[str, Any],
                   extra_headers: Optional[dict[str, str]] = None,
                   raw_payload: Optional[bytes] = None) -> dict[str, Any]:
        url = self._base + path
        headers = {
            'Content-Type': 'application/json',
            'User-Agent':   f'rstlic-sdk/1.1 splunkapp/{self._app_id}/{self._app_version}',
        }
        if extra_headers:
            headers.update(extra_headers)
        # Prefer caller-supplied bytes (used by heartbeat() to keep the
        # signed payload byte-identical to what we transmit) over a
        # re-serialisation that could reorder keys.
        payload = raw_payload if raw_payload is not None else json.dumps(body).encode('utf-8')
        try:
            status_code, text = self._http_post(url, headers, payload)
        except Exception as e:
            logger.warning('rstlic transport error: %s', e)
            raise RSTLicUnavailable(str(e))

        try:
            j = json.loads(text)
        except Exception:
            j = {}

        if status_code >= 500:
            raise RSTLicUnavailable(f'HTTP {status_code}: {text[:200]}')
        if status_code == 410:
            raise RSTLicRevoked(j.get('error') or text[:200])
        if status_code >= 400:
            raise RSTLicRejected(j.get('error') or text[:200])
        return j

    def _http_post(self, url: str, headers: dict[str, str], payload: bytes) -> tuple[int, str]:
        if requests is not None:
            r = requests.post(url, headers=headers, data=payload, timeout=self._timeout)
            return r.status_code, r.text
        # Fallback for environments without requests on sys.path.
        import urllib.request
        import urllib.error
        req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return resp.getcode(), resp.read().decode('utf-8')
        except urllib.error.HTTPError as e:
            return e.code, (e.read() or b'').decode('utf-8')
