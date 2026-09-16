"""Signed content packs — online prompt / template delivery (§ content-delivery).

Lets the vendor ship prompt / few-shot / detection-template updates to deployed
gateways WITHOUT rebuilding the image. A "content pack" is a signed token in the
exact license wire format ``<base64(json)>.<base64(rsa_pss_sig)>`` (so it reuses
``rstlic_verifier.verify_token`` and the same RSA public key trust), carrying:

    {
      "app_id": "rst_elastic_ai_copilot",
      "pack_version": "2026-07-01.1",        # sortable, monotonic (anti-rollback)
      "min_app_version": "1.1.0",
      "created_at": "...",
      "assets": {
        "prompt.nl2dsl.system":     {"kind": "prompt", "body": "..."},
        "prompt.explain.system":    {"kind": "prompt", "body": "..."},
        ...
      }
    }

Verification is MANDATORY and fail-closed: an unsigned / forged / wrong-app /
rolled-back pack is rejected and the current active pack stays. Embedded prompts
(``prompts._DEFAULT_*``) are the always-present floor — a missing/empty pack just
means the gateway uses the built-in defaults, so generation never breaks.

Storage (under the gateway state dir): ``content/packs/<version>.token`` +
``content/current.json`` pointer. Apply is atomic (write token → flip pointer →
reload cache). Offline import (admin endpoint) works today; an online channel
(heartbeat) can call ``apply`` with the same verification later.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .rstlic_verifier import LicenseError, verify_token

logger = logging.getLogger("rst.content_store")

APP_ID = "rst_elastic_ai_copilot"
APP_VERSION = os.environ.get("APP_VERSION", "1.1.0")

_active: dict[str, Any] | None = None
_active_meta: dict[str, Any] = {}
_loaded = False


# ── paths / keys ────────────────────────────────────────────────────────────

def _content_dir() -> Path:
    raw = os.environ.get("RST_CONTENT_DIR", "").strip()
    base = Path(raw) if raw else (Path(__file__).parent.parent / "content")
    return base


def _packs_dir() -> Path:
    return _content_dir() / "packs"


def _pointer_file() -> Path:
    return _content_dir() / "current.json"


def _write_pointer(payload: dict[str, Any]) -> None:
    """Atomically flip the active-pack pointer: write a temp file then
    ``os.replace`` it over ``current.json`` (rename is atomic on the same fs),
    so a crash mid-write can never leave a half-written / empty pointer."""
    pointer = _pointer_file()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    tmp = pointer.with_name(pointer.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, pointer)


def _public_pems() -> list[bytes]:
    """Trust anchors for content packs: a dedicated content key if configured,
    else the license public key (same signer trust). Multiple = key rotation."""
    pems: list[bytes] = []
    inline = os.environ.get("RST_CONTENT_PUBLIC_KEY", "").strip()
    if inline:
        pems.append(inline.encode("utf-8"))
    candidates = [
        os.environ.get("RST_CONTENT_PUBLIC_KEY_PATH", "").strip(),
        os.environ.get("RST_LICENSE_PUBLIC_KEY_PATH", "").strip(),
        str(Path(__file__).parent.parent / "keys" / "license_public.pem"),
    ]
    for path in candidates:
        if not path:
            continue
        try:
            pems.append(Path(path).read_bytes())
        except Exception:  # noqa: BLE001
            continue
    return pems


# ── verification ────────────────────────────────────────────────────────────

def verify_pack_token(token: str) -> dict[str, Any]:
    """Verify signature + envelope. Returns the validated pack dict or raises
    LicenseError (reused as the signed-content error type)."""
    pems = _public_pems()
    if not pems:
        raise LicenseError("no content public key configured")
    pack = verify_token(token.strip(), pems)  # RSA-PSS verify + decode
    if not isinstance(pack, dict):
        raise LicenseError("content pack payload is not an object")
    if pack.get("app_id") != APP_ID:
        raise LicenseError(f"content pack app_id mismatch: {pack.get('app_id')!r} != {APP_ID!r}")
    if not isinstance(pack.get("pack_version"), str) or not pack["pack_version"].strip():
        raise LicenseError("content pack missing pack_version")
    if not isinstance(pack.get("assets"), dict):
        raise LicenseError("content pack missing assets object")
    min_app = pack.get("min_app_version")
    if isinstance(min_app, str) and min_app.strip() and _ver_tuple(min_app) > _ver_tuple(APP_VERSION):
        raise LicenseError(
            f"content pack needs app >= {min_app}; this gateway is {APP_VERSION}. Upgrade the gateway."
        )
    return pack


def _ver_tuple(v: str) -> tuple[int, ...]:
    """App version → int tuple for the min_app_version gate. Each segment keeps
    only its *leading* digits ("0-rc1" → 0, not 01), non-numeric segments → 0,
    so "1.1.0-rc1" → (1, 1, 0)."""
    out: list[int] = []
    for part in str(v).split("."):
        m = re.match(r"\d+", part)
        out.append(int(m.group()) if m else 0)
    return tuple(out)


def _version_key(v: str) -> tuple[str, int]:
    """Order/compare pack versions of the form '2026-07-01.1'. Returns
    (date_part, suffix_int): the ISO date segment sorts lexicographically (=
    chronologically) and the '.N' suffix compares as an int so '.10' > '.9'."""
    s = str(v).strip()
    date_part, dot, suffix = s.rpartition(".")
    if not dot:  # no '.N' suffix — whole string is the date segment
        return (s, 0)
    try:
        return (date_part, int(suffix))
    except ValueError:
        return (s, 0)


# ── load / cache ────────────────────────────────────────────────────────────

def _load() -> None:
    global _active, _active_meta, _loaded
    _loaded = True
    _active, _active_meta = None, {}
    try:
        ptr = json.loads(_pointer_file().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return  # no active pack — defaults floor
    version = ptr.get("active_version")
    if not version:
        return
    try:
        token = (_packs_dir() / f"{version}.token").read_text(encoding="utf-8")
        pack = verify_pack_token(token)  # re-verify on load (tamper-evident at rest)
    except Exception as e:  # noqa: BLE001
        logger.warning("content_active_load_failed", extra={"version": version, "error": str(e)})
        return
    _active = pack
    _active_meta = {
        "active_version": version,
        "applied_at": ptr.get("applied_at"),
        "applied_by": ptr.get("applied_by"),
        "source": ptr.get("source"),
    }


def reload() -> None:
    """Drop the cache so the next get() re-reads the active pack from disk."""
    global _loaded
    _loaded = False


def get(asset_id: str, default: str) -> str:
    """Active pack's asset body, or the embedded default (the floor)."""
    if not _loaded:
        _load()
    if _active:
        asset = (_active.get("assets") or {}).get(asset_id)
        if isinstance(asset, dict):
            body = asset.get("body")
            if isinstance(body, str) and body.strip():
                return body
    return default


def active_version() -> str | None:
    if not _loaded:
        _load()
    return _active_meta.get("active_version") if _active else None


def active_sha() -> str | None:
    """sha256 of the currently-active pack token — the etag the online update
    channel (heartbeat) sends so the server can skip re-inlining an unchanged
    pack. Must match the server's ``content_packs.sha256`` = sha256(token).
    Returns None when no pack is active (server then always inlines)."""
    version = active_version()
    if not version:
        return None
    try:
        token = (_packs_dir() / f"{version}.token").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── apply / rollback / status ───────────────────────────────────────────────

def apply(token: str, *, actor: str | None, source: str = "offline") -> dict[str, Any]:
    """Verify + install + activate a content pack. Atomic, anti-rollback.
    Returns the new status. Raises LicenseError on a bad pack."""
    pack = verify_pack_token(token)
    version = pack["pack_version"]
    cur = active_version()
    if cur and _version_key(version) <= _version_key(cur):
        raise LicenseError(f"content pack {version} is not newer than active {cur} (rollback blocked)")

    _packs_dir().mkdir(parents=True, exist_ok=True)
    (_packs_dir() / f"{version}.token").write_text(token.strip(), encoding="utf-8")
    _write_pointer(
        {
            "active_version": version,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "applied_by": actor,
            "source": source,
        }
    )
    reload()
    logger.info("content_applied", extra={"version": version, "source": source, "actor": actor})
    return status()


def rollback(version: str, *, actor: str | None) -> dict[str, Any]:
    """Re-activate a previously-installed pack version (verify it still passes)."""
    token_path = _packs_dir() / f"{version}.token"
    if not token_path.exists():
        raise LicenseError(f"content pack version {version} is not in the local archive")
    verify_pack_token(token_path.read_text(encoding="utf-8"))  # still valid?
    _write_pointer(
        {
            "active_version": version,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "applied_by": actor,
            "source": "rollback",
        }
    )
    reload()
    logger.info("content_rolled_back", extra={"version": version, "actor": actor})
    return status()


def list_versions() -> list[str]:
    try:
        return sorted((p.stem for p in _packs_dir().glob("*.token")), key=_version_key)
    except Exception:  # noqa: BLE001
        return []


def status() -> dict[str, Any]:
    if not _loaded:
        _load()
    return {
        "active_version": _active_meta.get("active_version") if _active else None,
        "applied_at": _active_meta.get("applied_at"),
        "applied_by": _active_meta.get("applied_by"),
        "source": _active_meta.get("source"),
        "asset_count": len((_active or {}).get("assets") or {}),
        "available_versions": list_versions(),
        "signed": True,
    }
