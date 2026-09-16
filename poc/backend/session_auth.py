"""Single-operator password login (session cookie).

Why this exists: until now the product had three auth modes and none of them
was a login page. Caddy Basic Auth is a browser dialog the SPA never sees;
SSO hands off to the IdP's own page; demo mode has no auth at all. A
deployment that wants "open the URL, type a password" had nothing.

Scope is deliberately one account. The target deployment is single-user (one
analyst, own ELK), so there is no user table, no registration, no password
reset — the password lives in the environment as a hash and the operator
rotates it by editing `.env` and restarting. Anything more is a user-management
feature, not a login page.

The product ships with a working account (admin / Admin@123) so a fresh
install is usable, which means every deployment starts life with a password
anyone can look up. Changing it is the operator's first job, and the gateway
warns on every start until they do.

Configuration
-------------
    RST_ADMIN_USERNAME        account name, default "admin"
    RST_ADMIN_PASSWORD_HASH   scrypt hash; unset means the shipped default
    RST_SESSION_TTL_HOURS     session lifetime, default 12

Generate the hash (never put the plaintext in .env):

    python -m backend.session_auth 'your-password'

Interaction with the other two modes
------------------------------------
SSO wins. With RST_SSO_ENABLED on, password login is refused at startup — two
identity systems disagreeing about who you are is worse than either alone.
The shared secret is orthogonal and still applies: it authenticates the
*proxy chain*, this authenticates the *human*.

Session token
-------------
`v2.<session-id>.<expiry-epoch>.<hmac>`. The signing key and the record the id
names both live in `session_store` — see that module for why the key is no
longer derived from the password hash and why there is a server-side record at
all. Rotating the password still invalidates every session it issued; that is
now an explicit check rather than a side effect of the key changing.
"""

import base64
import hashlib
import hmac
import ipaddress
import logging
import os
import sys
import time

from starlette.requests import Request
from starlette.responses import Response

from . import session_store

logger = logging.getLogger("rst.session_auth")

COOKIE_NAME = "rst_session"
_TOKEN_VERSION = "v2"

# scrypt cost. n=16384 is ~50ms on a modern core — slow enough to make an
# offline dictionary attack on a leaked .env expensive, fast enough that a
# login feels instant.
_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1

DEFAULT_TTL_HOURS = 12.0

# Login throttle. Without it the password is one HTTP loop away from a
# dictionary attack — scrypt only raises the cost per guess, it does not
# limit how many guesses an attacker gets.
_MAX_FAILURES = 10
_FAILURE_WINDOW_S = 300.0
_failures: dict[str, list[float]] = {}
# 超过这么多个 key 就把过期的清一遍。没有它的话字典只增不减：`_spent` 只裁剪它
# 正好读到的那个 key，而一个轮换源地址来猜密码的攻击每次都换 key —— 挡是挡住了，
# 内存却一直涨。清掉过期项是行为中性的：窗口外的失败本来就不再算数。
_MAX_TRACKED_KEYS = 2048


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ───────────────────────────── password hashing ─────────────────────────────


def hash_password(password: str) -> str:
    """Return a self-describing scrypt hash string for `password`."""
    salt = os.urandom(16)
    key = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
        dklen=32,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64e(salt)}${_b64e(key)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of `password` against a stored scrypt hash.

    A malformed hash returns False rather than raising: a typo in .env must
    lock the operator out, never crash the request path into a 500 that some
    caller might treat as "not a rejection".
    """
    try:
        algo, n, r, p, salt_b64, key_b64 = stored.strip().split("$")
        if algo != "scrypt":
            return False
        expected = _b64d(key_b64)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=_b64d(salt_b64),
            n=int(n), r=int(r), p=int(p), dklen=len(expected),
        )
    except Exception:  # noqa: BLE001 — any malformed field means "no match"
        return False
    return hmac.compare_digest(actual, expected)


# ───────────────────────────── configuration ─────────────────────────────


# Shipped default credential: admin / Admin@123.
#
# The hash is a constant rather than computed at import because scrypt costs
# ~50ms and this is on the request path. A fixed salt leaks nothing here — the
# password it protects is printed in the docs.
#
# This is a KNOWN password. Every deployment that does not set
# RST_ADMIN_PASSWORD_HASH is one reachable port away from anyone who has read
# the manual, so `using_default_password()` drives a startup warning that
# repeats for as long as it is still in use.
DEFAULT_PASSWORD = "Admin@123"
DEFAULT_PASSWORD_HASH = (
    "scrypt$16384$8$1$dHWC7mwpZnsK81mU6_W-5w$gnc5HiMjyezadbwGXSxDl7u1uPUl98MqqlSYkKKvgmM"
)


def password_hash() -> str:
    return os.environ.get("RST_ADMIN_PASSWORD_HASH", "").strip() or DEFAULT_PASSWORD_HASH


def using_default_password() -> bool:
    return not os.environ.get("RST_ADMIN_PASSWORD_HASH", "").strip()


def default_password_blocks(ip: str) -> bool:
    """True when this login must be refused for still using the shipped password.

    The startup WARNING was the only thing standing between a fresh deployment
    and "known password on a reachable port" — a warning nobody reads once the
    thing works. So a remote login with the factory password is now refused
    outright: set `RST_ADMIN_PASSWORD_HASH` (that is the whole fix), or set
    `RST_ALLOW_DEFAULT_PASSWORD=1` if a LAN trial really does want the
    documented password.

    Loopback stays open so that first local login — the one where the operator
    is standing at the machine — still works and can be used to verify the
    deployment before the password is set.
    """
    if not using_default_password():
        return False
    if os.environ.get("RST_ALLOW_DEFAULT_PASSWORD", "").strip().lower() in {"1", "true", "yes"}:
        return False
    try:
        return not ipaddress.ip_address(ip.strip()).is_loopback
    except ValueError:
        # Unparseable / unknown source: treat as remote. Failing closed here
        # costs a config line; failing open costs the password.
        return True


DEFAULT_USERNAME = "admin"


def username() -> str:
    return os.environ.get("RST_ADMIN_USERNAME", "").strip() or DEFAULT_USERNAME


def verify_credentials(user: str, password: str) -> bool:
    """Check both halves, always paying the full scrypt cost.

    The password is verified even when the account is unknown or disabled, so a
    caller cannot tell those apart by how long the request took and go hunting
    for a valid account name first. Without a user database `user_db` answers
    from the environment, which is the single-operator behaviour this function
    had before.
    """
    from . import user_db

    rec = user_db.get(user.strip())
    stored = str(rec["password_hash"]) if rec else DEFAULT_PASSWORD_HASH
    pw_ok = verify_password(password, stored)
    return bool(rec) and not rec.get("disabled") and pw_ok


def login_enabled() -> bool:
    """True unless SSO owns identity — there is always a password (see above)."""
    # Imported lazily: auth.py imports this module at load time, so a
    # module-level import here would be a cycle.
    from .auth import sso_enabled

    return not sso_enabled()


def ttl_seconds() -> float:
    raw = os.environ.get("RST_SESSION_TTL_HOURS", "").strip()
    try:
        hours = float(raw) if raw else DEFAULT_TTL_HOURS
    except ValueError:
        logger.warning(
            "session_ttl_invalid — RST_SESSION_TTL_HOURS=%r is not a number, "
            "using %sh", raw, DEFAULT_TTL_HOURS,
        )
        hours = DEFAULT_TTL_HOURS
    if hours <= 0:
        return DEFAULT_TTL_HOURS * 3600.0
    return hours * 3600.0


# ───────────────────────────── session token ─────────────────────────────
#
# `v2.<sid>.<expiry-epoch>.<hmac>`. Two changes from v1, both required before
# more than one person can hold a session:
#
#   * The signing key comes from session_store, not from the password hash.
#     Deriving it from the password made "change the password" sign everyone
#     out — a convenience with one account, a shared-fate bug with several.
#     The sign-out behaviour is kept deliberately instead (session_store
#     records the password fingerprint each session was issued under).
#   * The token names a server-side record, so a session can be withdrawn.
#     v1 carried an expiry and nothing else; there was no way to answer "who
#     is this" or to make a leaked token stop working before it aged out.
#
# v1 tokens are not accepted. They cannot be: their key no longer exists and
# they name no one. Upgrading signs everybody in again, once.


def account_password_hash(user: str) -> str:
    """Stored hash for `user`, or the configured one when the account is gone.

    Falling back keeps a session whose account was deleted failing the
    fingerprint check rather than crashing — deleted is "no longer valid", the
    same answer as a changed password.
    """
    from . import user_db

    return user_db.password_hash_of(user) or password_hash()


def issue_token(user: str | None = None, roles: list[str] | None = None,
                now: float | None = None) -> str:
    """Issue a session for `user` (the configured account by default).

    The role recorded here is display-only. Authorisation reads the live role
    from `user_db` on every request, because a session that carried its own
    role would keep the privileges it was issued with until it expired — and
    "change a role and it takes effect now" is the point of having roles.
    """
    t = now if now is not None else time.time()
    name = user if user is not None else username()
    exp = int(t + ttl_seconds())
    if roles is None:
        from . import user_db

        roles = [user_db.role_of(name) or user_db.DEFAULT_ROLE]
    sid = session_store.create(
        name, roles, float(exp),
        session_store.password_fingerprint(account_password_hash(name)), now=t,
    )
    payload = f"{_TOKEN_VERSION}.{sid}.{exp}"
    sig = hmac.new(session_store.signing_key(), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{_b64e(sig)}"


def token_identity(token: str, now: float | None = None) -> dict[str, object] | None:
    """The identity behind a session token, or None if it is not a live session.

    Signature first, expiry second, the server-side record last — an unsigned
    token must never get as far as having its claimed expiry believed, and a
    signed-but-withdrawn one must not get in on its signature alone.
    """
    try:
        version, sid, exp_s, sig_b64 = token.split(".")
        if version != _TOKEN_VERSION:
            return None
        payload = f"{version}.{sid}.{exp_s}"
        expected = hmac.new(
            session_store.signing_key(), payload.encode(), hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(_b64d(sig_b64), expected):
            return None
        t = now if now is not None else time.time()
        if t >= int(exp_s):
            return None
    except Exception:  # noqa: BLE001 — anything unparseable is not a session
        return None
    rec = session_store.lookup(sid, now=now)
    if not rec:
        return None
    name = str(rec.get("username") or "")
    # The password this session was issued under must still be the account's
    # current one, and the account must still be usable. Disabling someone has
    # to take their live sessions with it — `revoke_all` does that at the
    # moment of disabling, and this is what closes the race with a request
    # already in flight, and with a session issued by another worker.
    if rec.get("pw_fp") != session_store.password_fingerprint(account_password_hash(name)):
        return None
    from . import user_db

    role = user_db.role_of(name)
    if role is None:
        return None
    return {
        "username": name,
        "roles": [role],
        "source": "password",
        "sid": sid,
    }


def token_valid(token: str, now: float | None = None) -> bool:
    return token_identity(token, now=now) is not None


def session_identity(request: Request) -> dict[str, object] | None:
    """Identity of the session cookie on this request, or None.

    This is what makes `auth.current_user()` able to answer under password
    login. Until now it could not: it only read SSO headers, so audit records
    went out without a user and every analyst's history landed in one bucket.
    """
    if not login_enabled():
        return None
    ident = token_identity(request.cookies.get(COOKIE_NAME, ""))
    if ident is not None:
        # The session id stays internal. This dict is what /api/me serialises to
        # the browser and what audit records store as `user`; a session handle
        # belongs in neither, and the audit index has no field for it.
        ident.pop("sid", None)
    return ident


def session_valid(request: Request) -> bool:
    """True when this request carries a valid, unexpired session cookie."""
    return session_identity(request) is not None


def revoke_session(request: Request) -> None:
    """Withdraw the session this request is carrying, server-side.

    Logout used to delete the cookie and nothing else, which asks the browser
    to forget a credential that still worked for up to 12 hours.
    """
    ident = token_identity(request.cookies.get(COOKIE_NAME, ""))
    if ident and ident.get("sid"):
        session_store.revoke(str(ident["sid"]))


def request_is_https(request: Request) -> bool:
    """True when the BROWSER reached us over HTTPS, proxy hops included.

    `request.url.scheme` is the scheme of the last hop, and this product's
    documented deployment terminates TLS at Caddy and forwards plain HTTP. So
    the scheme check alone reported "http" on every real HTTPS deployment and
    the session cookie went out without `Secure` — the one case it was written
    to cover. `X-Forwarded-Proto` is what the proxy sets to say what the
    browser actually used.

    A client that forges the header only hurts itself: claiming `https` on a
    plain-HTTP deployment makes the browser drop the cookie it was just given.
    """
    fwd = request.headers.get("x-forwarded-proto", "")
    if fwd:
        # Leftmost hop = the one that faced the browser.
        return fwd.split(",")[0].strip().lower() == "https"
    return request.url.scheme == "https"


def set_session_cookie(response: Response, request: Request,
                      user: str | None = None) -> None:
    response.set_cookie(
        COOKIE_NAME,
        issue_token(user),
        max_age=int(ttl_seconds()),
        httponly=True,
        samesite="lax",
        # Secure only over HTTPS — setting it unconditionally would silently
        # drop the cookie on the plain-HTTP LAN deployments this product ships to.
        secure=request_is_https(request),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


# ───────────────────────────── login throttle ─────────────────────────────


def _account_key(user: str) -> str:
    """Namespaced so an account named like an IP cannot share its budget."""
    return f"user:{user.strip().casefold()}"


def _spent(key: str, now: float | None = None) -> bool:
    t = now if now is not None else time.time()
    recent = [ts for ts in _failures.get(key, []) if t - ts < _FAILURE_WINDOW_S]
    _failures[key] = recent
    return len(recent) >= _MAX_FAILURES


def throttled(ip: str, user: str = "", now: float | None = None) -> bool:
    """True when this login attempt has spent a failed-login budget.

    Two budgets, either of which can be exhausted: one per source IP, one per
    account name. The IP budget alone let an attacker rotate addresses and keep
    guessing one account for as long as they liked; the account budget is what
    actually protects a password.

    ponytail: budgets live in process memory, so multiple workers each hold
    their own and a restart clears them. The shipped image runs a single
    uvicorn worker (Dockerfile:136 — no `--workers`), so today that is the
    whole picture. Move to the shared store when the gateway is scaled out.
    """
    if _spent(ip, now):
        return True
    return bool(user.strip()) and _spent(_account_key(user), now)


def _prune(now: float) -> None:
    """丢掉窗口外的失败记录。只在 key 数超过上限时扫全表，正常部署上永远不跑。"""
    if len(_failures) <= _MAX_TRACKED_KEYS:
        return
    stale = [k for k, ts in _failures.items() if all(now - t >= _FAILURE_WINDOW_S for t in ts)]
    for k in stale:
        del _failures[k]
    if len(_failures) > _MAX_TRACKED_KEYS:
        logger.warning(
            "login_throttle_table_large — %d 个来源/账号在 %.0fs 窗口内有失败记录，"
            "可能正在被撞库", len(_failures), _FAILURE_WINDOW_S,
        )


def record_failure(ip: str, user: str = "", now: float | None = None) -> None:
    t = now if now is not None else time.time()
    _prune(t)
    _failures.setdefault(ip, []).append(t)
    if user.strip():
        _failures.setdefault(_account_key(user), []).append(t)


def clear_failures(ip: str, user: str = "") -> None:
    _failures.pop(ip, None)
    if user.strip():
        _failures.pop(_account_key(user), None)


def _reset_throttle_for_tests() -> None:
    _failures.clear()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m backend.session_auth '<password>'", file=sys.stderr)
        print("prints the RST_ADMIN_PASSWORD_HASH value to put in .env", file=sys.stderr)
        raise SystemExit(2)
    print(hash_password(sys.argv[1]))
    # compose interpolates `$` in .env, so a raw scrypt hash gets truncated to
    # "scrypt$16384$8$1-" and every login fails. Say so where the hash is minted.
    print("写进 .env 时把每个 $ 双写成 $$(docker compose 会把 $x 当变量展开)。", file=sys.stderr)
