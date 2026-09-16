"""Stable per-install identifier for license binding.

Generated once on first run, persisted in <install_dir>/server_guid (chmod 600 on
POSIX). Heartbeat additionally reports ES cluster.uuid + cluster.name as
non-identity audit metadata (see decision #2 in reference_rst_platform_license).
"""

import os
import uuid
from pathlib import Path
from typing import Any, Optional

_DEFAULT_GUID_FILE = Path(__file__).parent.parent / "server_guid"
_GUID_FILE = Path(os.environ.get("RST_SERVER_GUID_FILE", str(_DEFAULT_GUID_FILE)))

_cached_guid: Optional[str] = None
_cached_cluster_meta: Optional[dict[str, Any]] = None
_cached_fingerprint: Optional[str] = None


def get_server_guid() -> str:
    """Return the stable server GUID, generating + persisting on first call."""
    global _cached_guid
    if _cached_guid:
        return _cached_guid
    if _GUID_FILE.exists():
        try:
            text = _GUID_FILE.read_text(encoding="utf-8").strip()
            uuid.UUID(text)
            _cached_guid = text
            return _cached_guid
        except (ValueError, OSError):
            pass  # invalid contents — regenerate
    new = str(uuid.uuid4())
    _GUID_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _GUID_FILE.with_suffix(_GUID_FILE.suffix + ".tmp")
    tmp.write_text(new, encoding="utf-8", newline="\n")
    os.replace(tmp, _GUID_FILE)
    try:
        os.chmod(_GUID_FILE, 0o600)
    except OSError:
        pass  # best effort on Windows
    _cached_guid = new
    return _cached_guid


_APP_ID = "rst_elastic_ai_copilot"


def get_host_fingerprint() -> str:
    """SEC-FP-1 hardware-rooted fingerprint (recipe v2), used to bind a license
    activation to this machine.

    machine-id is the identity root; the primary MAC is folded in only when no
    machine-id is readable (some containers). server_guid + app_id are salt.
    Cached after the first call. Raises ``RSTLicHardwareUnavailable`` when no
    hardware identifier can be read at all.
    """
    global _cached_fingerprint
    if _cached_fingerprint:
        return _cached_fingerprint
    from rstlic_client import RSTLicClient
    _cached_fingerprint = RSTLicClient.fingerprint(
        server_guid=get_server_guid(),
        app_id=_APP_ID,
    )
    return _cached_fingerprint


