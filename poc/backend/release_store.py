"""Gateway release downloader + staging (P3).

Consumes the ``release`` block a heartbeat surfaces (design §4.1) and downloads
the image/artifact tarballs to a staging area, verifying the signed manifest
and every artifact sha256 before anything lands. It does NOT install — that is
``rst-update.sh`` (P4). Installation reads the staged release; this module only
gets a *verified, complete* release onto disk, fail-closed.

Guarantees (design §9/§10/§15):
  * The manifest is RSA-PSS verified (same trust as content packs) before use.
  * ``min_updater_version`` gate: refuse + actionable message if the local
    ``rst-update.sh`` is too old to install this release (§8).
  * Disk space is checked up front (manifest sizes) — never leave a half file.
  * Each artifact streams to ``<sha>.part`` while hashing; a sha256 mismatch
    wipes staging and leaves the current install/pointer untouched (the core
    fail-closed invariant).
  * The staged pointer flips atomically and only after every artifact verified.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import content_store
from .rstlic_verifier import LicenseError, verify_token

logger = logging.getLogger("rst.release_store")

APP_ID = "rst_elastic_ai_copilot"
APP_VERSION = os.environ.get("APP_VERSION", "1.1.0")
# Capability version of the on-host rst-update.sh installer. A release whose
# manifest requires a newer updater than this is refused (§8).
try:
    UPDATER_VERSION = int(os.environ.get("RST_UPDATER_VERSION", "1"))
except ValueError:
    UPDATER_VERSION = 1
# Refuse to stage unless this much slack remains after the download.
DISK_MARGIN = 256 * 1024 * 1024  # 256 MB
_HEX = set("0123456789abcdef")


class ReleaseError(Exception):
    """Manifest rejected, disk short, updater too old, or artifact mismatch."""


class ManifestVerifyError(ReleaseError):
    """Signature / app_id / sha256 verification failure — an intrusion signal
    (tampering in transit or probing). Reported to the license server (§11)."""


# ── paths ────────────────────────────────────────────────────────────────────

def _release_dir() -> Path:
    raw = os.environ.get("RST_RELEASE_DIR", "").strip()
    return Path(raw) if raw else (Path(__file__).parent.parent / "release")


def _staging_dir() -> Path:
    return _release_dir() / "staging"


def _pointer_file() -> Path:
    return _release_dir() / "current.json"


def _ver_tuple(v: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in str(v or "").split("."):
        digits = ""
        for c in part:
            if c.isdigit():
                digits += c
            else:
                break
        out.append(int(digits) if digits else 0)
    return tuple(out)


def _reset_staging() -> None:
    """Wipe the staging dir wholesale (removes stale .part + partial artifacts).
    Never touches the pointer — the current install stays intact."""
    staging = _staging_dir()
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)


def _write_pointer(payload: dict[str, Any]) -> None:
    pointer = _pointer_file()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    tmp = pointer.with_name(pointer.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, pointer)


# ── verification ─────────────────────────────────────────────────────────────

def verify_manifest(token: str) -> dict[str, Any]:
    """RSA-PSS verify the manifest + envelope checks. Raises ReleaseError."""
    pems = content_store._public_pems()
    if not pems:
        raise ReleaseError("no content public key configured")
    try:
        manifest = verify_token(token.strip(), pems)
    except LicenseError as e:
        raise ManifestVerifyError(f"manifest signature/verify failed: {e}")
    if not isinstance(manifest, dict):
        raise ManifestVerifyError("manifest is not an object")
    if manifest.get("app_id") != APP_ID:
        raise ManifestVerifyError(f"manifest app_id mismatch: {manifest.get('app_id')!r}")
    version = manifest.get("release_version")
    if not isinstance(version, str) or not version.strip():
        raise ReleaseError("manifest missing release_version")
    arts = manifest.get("artifacts")
    if not isinstance(arts, list) or not arts:
        raise ReleaseError("manifest missing artifacts")
    for a in arts:
        sha = a.get("sha256") if isinstance(a, dict) else None
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in _HEX for c in sha):
            raise ManifestVerifyError("manifest artifact sha256 must be 64 hex")
    min_up = manifest.get("min_updater_version") or 0
    if isinstance(min_up, int) and min_up > UPDATER_VERSION:
        raise ReleaseError(
            f"this release needs updater version >= {min_up}, but this host has "
            f"{UPDATER_VERSION}. Download the newer rst-update.sh from the customer "
            f"console and re-run before installing."
        )
    return manifest


# ── download + stage ─────────────────────────────────────────────────────────

def _default_fetch_text(url: str) -> str:
    # httpx, not requests: requests is not in the shipped image (requirements.lock
    # has httpx only), so every customer that reached this point got
    # "No module named 'requests'" and online update never worked from a
    # delivered bundle — caught on the 2026-09-17 demo box.
    import httpx
    r = httpx.get(url, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.text


def _default_download_to(url: str, dest: Path) -> str:
    """Stream url -> dest while hashing; return the sha256 hex actually written."""
    import httpx
    h = hashlib.sha256()
    with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)
                    h.update(chunk)
    return h.hexdigest()


def download_and_stage(
    release: dict[str, Any],
    *,
    fetch_text: Optional[Callable[[str], str]] = None,
    download_to: Optional[Callable[[str, Path], str]] = None,
    on_verify_failed: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Fetch + verify the manifest, then download + verify every artifact into a
    fresh staging dir. Returns status(). Raises ReleaseError fail-closed.

    ``on_verify_failed(reason)`` is invoked on a signature/sha verification
    failure (ManifestVerifyError) so the caller can report it to the license
    server (§11). Its own exceptions are swallowed — reporting must not mask
    the original failure."""
    fetch_text = fetch_text or _default_fetch_text
    download_to = download_to or _default_download_to
    try:
        return _download_and_stage(release, fetch_text, download_to)
    except ManifestVerifyError as exc:
        if on_verify_failed is not None:
            try:
                on_verify_failed(str(exc))
            except Exception as e:  # noqa: BLE001
                logger.warning("verify-failed report hook errored: %s", e)
        raise


def _download_and_stage(release, fetch_text, download_to) -> dict[str, Any]:
    if not isinstance(release, dict) or not release.get("manifest_url"):
        raise ReleaseError("release payload missing manifest_url")

    # 1. manifest: fetch + verify signature/envelope/updater gate.
    manifest = verify_manifest(fetch_text(release["manifest_url"]))
    version = manifest["release_version"]
    if _ver_tuple(version) <= _ver_tuple(APP_VERSION):
        raise ReleaseError(f"release {version} is not newer than running {APP_VERSION}")
    signed_shas = {a["sha256"] for a in manifest["artifacts"]}

    # 2. disk check up front — never start if we can't finish.
    need = sum(int(a.get("size") or 0) for a in manifest["artifacts"])
    _release_dir().mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(_release_dir()).free
    if free < need + DISK_MARGIN:
        raise ReleaseError(
            f"insufficient disk: need ~{need} bytes + margin, {free} free")

    # 3. fresh staging, then download each artifact the heartbeat advertised.
    _reset_staging()
    staged: list[dict[str, Any]] = []
    for a in (release.get("artifacts") or []):
        sha = a.get("sha256")
        if sha not in signed_shas:
            # Server-provided metadata lied about which artifacts exist — the
            # signed manifest is the authority. Abort fail-closed.
            _reset_staging()
            raise ManifestVerifyError(f"artifact {sha} not present in the signed manifest")
        part = _staging_dir() / f"{sha}.part"
        got = download_to(a["url"], part)
        if got != sha:
            _reset_staging()  # wipe partial; pointer/current untouched
            raise ManifestVerifyError(f"sha256 mismatch for {a.get('kind')} artifact")
        os.replace(part, _staging_dir() / sha)
        staged.append({"kind": a.get("kind"), "sha256": sha, "size": a.get("size")})

    # 4. flip the staged pointer atomically — only after everything verified.
    #    The pointer is what rst-update.sh (P4) reads to install; it records the
    #    verified manifest so the installer needn't re-fetch.
    _write_pointer({
        "staged_version": version,
        "manifest": manifest,
        "artifacts": staged,
        "min_updater_version": manifest.get("min_updater_version") or 0,
        "staged_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info("release_staged", extra={"version": version, "artifacts": len(staged)})
    return status()


# ── status ───────────────────────────────────────────────────────────────────

def _sweep_parts() -> None:
    staging = _staging_dir()
    if not staging.exists():
        return
    for p in staging.glob("*.part"):
        try:
            p.unlink()
        except OSError:
            pass


def status() -> dict[str, Any]:
    """Current staged-release state for the admin UI. Sweeps orphan .part files
    (e.g. a download interrupted by a restart) as a side effect."""
    _sweep_parts()
    out: dict[str, Any] = {
        "running_version": APP_VERSION,
        "updater_version": UPDATER_VERSION,
        "staged_version": None,
        "artifacts": [],
        "staged_at": None,
    }
    try:
        ptr = json.loads(_pointer_file().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return out
    out["staged_version"] = ptr.get("staged_version")
    out["artifacts"] = ptr.get("artifacts") or []
    out["staged_at"] = ptr.get("staged_at")
    out["min_updater_version"] = ptr.get("min_updater_version")
    return out
