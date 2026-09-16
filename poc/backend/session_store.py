"""Server-side session records, and the key that signs them.

Two things the single-operator design could do without and a multi-user one
cannot:

**A signing key that is not the password.** Sessions used to be signed with a
key derived from the password hash, which made "change the password" mean
"sign everyone out" for free. With more than one account that stops being a
feature: whoever changes their password would sign out the whole team. The key
now lives here — generated once, persisted, never rotated on its own — and the
sign-out-on-password-change behaviour is preserved deliberately instead, by
recording which password hash each session was issued under and refusing the
ones that no longer match.

**A record of what is outstanding.** A signed token alone cannot be withdrawn:
`logout` could only delete the cookie the browser was already free to keep, and
"disable this employee" would have meant nothing until their token expired. So
each session is written down, and dropping the record is what makes it stop
working.

Storage is one JSON file under the state volume, the same place the license key
and server GUID live. ponytail: process-local file, no locking beyond an atomic
replace — the shipped image runs a single uvicorn worker (Dockerfile has no
`--workers`). Move this to the user database when the gateway is scaled out or
when the user store lands; the call sites here are the whole interface.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("rst.session_store")

_DEFAULT_FILE = Path(__file__).parent.parent / "sessions.json"


def _store_path() -> Path:
    return Path(os.environ.get("RST_SESSION_STORE", "").strip() or _DEFAULT_FILE)


# Cached per path so a test that repoints RST_SESSION_STORE gets a fresh store
# instead of the previous file's key.
_cache: dict[str, dict[str, Any]] = {}


def _blank() -> dict[str, Any]:
    return {"key": secrets.token_hex(32), "sessions": {}}


def _load() -> dict[str, Any]:
    path = _store_path()
    cached = _cache.get(str(path))
    if cached is not None:
        return cached
    data: dict[str, Any] | None = None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("key"), str) and raw["key"]:
            raw.setdefault("sessions", {})
            data = raw
    except (OSError, ValueError):
        data = None
    if data is None:
        # Unreadable or corrupt: start over rather than run without a key. The
        # cost is that everyone signs in again, which is the safe direction.
        data = _blank()
        _cache[str(path)] = data
        _flush()
        return data
    _cache[str(path)] = data
    return data


def _flush() -> None:
    path = _store_path()
    data = _cache.get(str(path))
    if data is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8", newline="\n")
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass  # best effort on Windows
    except OSError:
        # A read-only state volume must not take the gateway down; sessions
        # then live for this process only and are gone on restart.
        logger.warning("session_store_write_failed — path=%s", path, exc_info=True)


def signing_key() -> bytes:
    return bytes.fromhex(_load()["key"])


def password_fingerprint(password_hash: str) -> str:
    """Short digest of the stored password hash, recorded on each session.

    Comparing it at lookup time is what keeps "changing the password signs out
    the sessions it issued" true now that the signing key no longer moves.
    """
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def _prune(sessions: dict[str, Any], now: float) -> None:
    for sid in [s for s, r in sessions.items() if r.get("exp", 0) <= now]:
        sessions.pop(sid, None)


def create(username: str, roles: list[str], exp: float, pw_fp: str,
           now: float | None = None) -> str:
    t = now if now is not None else time.time()
    data = _load()
    sessions = data["sessions"]
    _prune(sessions, t)
    sid = secrets.token_urlsafe(16)
    sessions[sid] = {
        "username": username,
        "roles": list(roles),
        "issued_at": t,
        "exp": exp,
        "pw_fp": pw_fp,
    }
    _flush()
    return sid


def lookup(sid: str, now: float | None = None) -> dict[str, Any] | None:
    """The live record for `sid`, or None if it is expired or revoked.

    The password-fingerprint check that used to live here moved up to
    `session_auth.token_identity`. With one account there was one password
    hash and this function could fetch it; with a user table the hash to
    compare against is the one belonging to *this session's* user, which is a
    name only the record itself carries. Doing the comparison after the lookup
    keeps the store ignorant of how accounts are stored, which is the whole
    reason it can stay a JSON file while users live in Postgres.
    """
    t = now if now is not None else time.time()
    rec = _load()["sessions"].get(sid)
    if not rec:
        return None
    if rec.get("exp", 0) <= t:
        return None
    return rec


def revoke(sid: str) -> None:
    if _load()["sessions"].pop(sid, None) is not None:
        _flush()


def revoke_all(username: str | None = None) -> int:
    """Drop every session, or every session belonging to one account.

    This is the "force sign-out" the product could not perform: logout only
    deleted a cookie, so a leaked token stayed valid for its full TTL.
    """
    sessions = _load()["sessions"]
    doomed = [
        sid for sid, rec in sessions.items()
        if username is None or rec.get("username") == username
    ]
    for sid in doomed:
        sessions.pop(sid, None)
    if doomed:
        _flush()
    return len(doomed)


def _reset_for_tests() -> None:
    _cache.clear()
