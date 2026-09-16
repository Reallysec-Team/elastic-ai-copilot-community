"""Shared-secret + admin-token auth middleware.

Two layers:

1. **SharedSecretMiddleware** — gates every `/api/*` request behind
   `X-RST-Gateway-Token: <secret>` when `RST_GATEWAY_SHARED_SECRET` is set.
   Health probes (`/healthz`, `/readyz`), license read endpoints
   (`/api/license/status`, `/api/license/activate`, `/api/license/quota`) and
   the SPA itself bypass — they need to work before the gateway is fully
   configured. **`/api/license/server-guid` is NOT in the bypass** anymore
   (Round 9-A) since the GUID is a binding key and leaking it weakens the
   license server's identity-binding lookup.

2. **`require_admin(request)`** — helper for routes that mutate
   security-sensitive config (`/api/settings`, `/api/llm/providers/save`).
   Requires `X-RST-Admin-Token` matching `RST_ADMIN_TOKEN`. If
   `RST_ADMIN_TOKEN` is unset, the gateway only accepts these calls from
   `127.0.0.1` / `::1` (so dev still works on the same host). Reject
   otherwise.

The split lets us keep "plugin-to-gateway" calls (shared secret) separate
from "operator changes config" (admin token) — two different threat
models, two different keys.

Standalone UI at the gateway origin won't work when the secret is enforced
(the JS client has no way to know the secret). In production deployments the
static UI should be disabled or fronted by a reverse proxy that injects the
header.
"""

import hmac
import logging
import os
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from .api_errors import ApiError, error_payload
from .user_state import PERSONAL_KINDS

from .session_auth import (
    login_enabled,
    session_identity,
    session_valid,
    using_default_password,
)

logger = logging.getLogger("rst.auth")

SHARED_SECRET_HEADER = "X-RST-Gateway-Token"
ADMIN_TOKEN_HEADER = "X-RST-Admin-Token"

# Public read-only license endpoints — bypass shared-secret since the UI
# needs them before the operator configures anything.
# NOTE: license/activate + license/reload are NOT here anymore — when a shared
# secret is configured they must carry it (they mutate licensing state, so a
# direct/unauthenticated caller must not reach them). They remain always-allowed
# at the *license gate* (license_gate.py) so a lapsed license can still be
# re-activated — that exemption is independent of this shared-secret bypass.
_BYPASS_PATHS = {
    "/healthz",
    "/readyz",
    "/api/license/status",
    "/api/license/quota",
    "/api/me",
}
# NOTE: /api/license/server-guid intentionally NOT in bypass — GUID is a
# binding key. The activation page hits it from same origin and will need
# the shared secret in production.

# Endpoints that must stay reachable even when RST_SSO_ENFORCE rejects
# anonymous requests, so the gateway can boot and a lapsed license can be
# re-activated before any verified identity exists. This is the SSO-enforce
# exemption only — shared-secret gating still follows _BYPASS_PATHS above.
_ENFORCE_EXEMPT_PATHS = {
    "/healthz",
    "/readyz",
    # 机器入口，见 _LOGIN_EXEMPT_PATHS 里同一条的注释。
    "/api/alerts/ingest",
    "/api/license/status",
    "/api/license/activate",
    "/api/license/quota",
    "/api/license/reload",
    "/api/license/server-guid",
    "/api/me",
}

# Reachable without a session when password login is on. Deliberately short:
# the login form itself, the probe the SPA uses to decide whether to show it,
# and the health probes an orchestrator calls before anyone has logged in.
# License endpoints are NOT here — activating a license is an operator action,
# and the operator has the password.
_LOGIN_EXEMPT_PATHS = {
    "/healthz",
    "/readyz",
    "/api/me",
    "/api/auth/login",
    "/api/auth/logout",
    # 告警接入源 B。Kibana 的 webhook connector 只能挂静态 header，拿不到会话
    # cookie，所以登录闸会在它自己那道 token 比对之前把它 401 掉 —— 客户按
    # .env.example 配完，产品这边一点痕迹都没有，只有 Kibana 自己的日志里有个
    # 401。它不是无鉴权入口：secret 没设时整条 403，设了就常量时间比对
    # X-RST-Alert-Token（alerts_routes.ingest_webhook）。共享密钥闸照旧适用。
    "/api/alerts/ingest",
}

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# 每人自己的界面状态（查询历史、偏好、保存的查询、分诊标记）走
# PUT/DELETE /api/state/...。按方法判会把它们一并拦掉，于是只读账号连自己的主题和
# 语言都存不下来 —— 而这既不是共享状态，也没有别人看得见：和白名单里那几条
# 「落一条 owner 隔离的记录」是同一性质。
#
# 只豁免 user_state.PERSONAL_KINDS 那几种。/api/state/ 整个前缀曾经一起豁免，
# 结果只读账号能 PUT /api/state/alert_status/…，把一条告警替全班标成「已处置」
# —— 那是 SHARED_KINDS（_team 桶），是团队事实，不是个人偏好。
# 别的写接口照旧按方法拦，新加的路由默认仍然是拦住的。
_WRITE_EXEMPT_PREFIXES = tuple(sorted(f"/api/state/{k}/" for k in PERSONAL_KINDS))

# The three POSTs a read-only account must still be able to make: get in, get
# out, and change its own password. Everything else that changes state is
# somebody else's job.
_WRITE_EXEMPT_PATHS = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/password",
}

# POSTs that are read operations wearing a POST because the query goes in the
# body: ask a question, run the search, look something up. Without them
# "read-only" degrades to "can do nothing at all" — the whole query surface,
# the KB lookup and both explain dialogs are POSTs. Everything they persist is
# the caller's own trace (conversation turns, analysis records — all
# owner-scoped) or the audit log, which every read writes anyway.
_READ_ONLY_POST_PATHS = {
    "/api/generate",
    "/api/generate/stream",
    "/api/execute",
    "/api/kibana-link",
    "/api/explain-log",
    "/api/explain-result",
    # 「再想几个角度」只出问句，不碰数据。
    "/api/suggest-angles",
    "/api/kb/search",
    "/api/platform/interpret",
    # 字段字典是纯查询（读 mapping + 采样），只是把索引名放在 body 里。
    "/api/field-dict",
    # 调查 / 分诊那一类是同样的读语义：只读告警、跑一轮分析、落一条 owner 隔离的
    # 记录。少了它们，viewer 在告警页点「调查」直接 403 —— 而这正是只读账号最该
    # 能做的事（看懂发生了什么），不是改动。
    "/api/investigate-alert",
    "/api/investigate-alert/stream",
    "/api/triage/batch",
    # 测 ES 连通性是探活：拨一次号，什么都不写。真正的写在 POST /api/settings。
    "/api/settings/es/test",
    "/api/detection-rule/generate",
    "/api/report/incident",
}


def _shared_secret() -> str:
    return os.environ.get("RST_GATEWAY_SHARED_SECRET", "").strip()


def _admin_token() -> str:
    return os.environ.get("RST_ADMIN_TOKEN", "").strip()


def _has_admin_token(request: Request) -> bool:
    """True when the caller presents the configured ops token.

    This is the machine door. Ops curl, CI and scheduled jobs authenticate with
    RST_ADMIN_TOKEN and have no way to hold a browser session, so the login gate
    lets them past on this alone. Note it is NOT the same as passing the shared
    secret: Caddy injects that into browser traffic too, so honouring it would
    hand every browser a way around the login page.
    """
    token = _admin_token()
    if not token:
        return False
    return hmac.compare_digest(request.headers.get(ADMIN_TOKEN_HEADER, ""), token)


class SharedSecretMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        if login_enabled() and using_default_password():
            logger.warning(
                "DEFAULT PASSWORD IN USE — this deployment still accepts the "
                "shipped credential (admin / Admin@123), which is published in "
                "the docs and therefore known to anyone who can reach this "
                "gateway. Generate a hash with `python -m backend.session_auth "
                "'<new-password>'` and set RST_ADMIN_PASSWORD_HASH in .env. "
                "Changing it also signs out every existing session."
            )
        elif login_enabled():
            logger.info(
                "password_login_enabled — gated /api/* calls require a session "
                "cookie from /api/auth/login."
            )
        else:
            logger.info(
                "password_login_disabled — RST_SSO_ENABLED is on, so SSO owns "
                "identity and the password account is not accepted."
            )
        # The DEMO MODE banner claims there is NO authentication — a configured
        # password is authentication, so it must not fire in that case.
        if not login_enabled() and not _shared_secret() and not _admin_token():
            logger.warning(
                "DEMO MODE — both RST_GATEWAY_SHARED_SECRET and RST_ADMIN_TOKEN "
                "are unset. The gateway has NO authentication; every endpoint "
                "(including admin) is open to anyone who reaches it. OK for an "
                "isolated dev / Docker Desktop / single-user box; NEVER expose "
                "this configuration to a LAN or the internet. Set both vars and "
                "front with Caddy for production."
            )
        elif not _shared_secret():
            logger.warning(
                "shared_secret_unset — RST_GATEWAY_SHARED_SECRET is not set. "
                "Gateway runs with no shared-secret auth. OK for dev; set this in production."
            )
        elif not _admin_token():
            logger.warning(
                "admin_token_unset — RST_ADMIN_TOKEN is not set; ops curl/CI from "
                "outside the proxy chain has no way to call admin endpoints. UI access "
                "still works via the shared-secret proxy chain."
            )
        # Orthogonal warning: SSO on but no shared secret → identity headers
        # are forgeable by any direct caller, so we refuse to trust them and
        # SSO provides NO real protection. Warn loudly so ops don't assume it does.
        if sso_enabled() and not _shared_secret():
            logger.warning(
                "sso_identity_untrusted — RST_SSO_ENABLED is on but "
                "RST_GATEWAY_SHARED_SECRET is unset. The forward-auth identity "
                "headers (X-Auth-Request-*) are NOT trusted (a direct client could "
                "forge them to impersonate users/admins); every request falls back "
                "to anonymous / non-admin. Set RST_GATEWAY_SHARED_SECRET and only "
                "expose the gateway via the forward-auth proxy for SSO to protect anything."
            )

    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path

        # Static files / non-API paths pass through.
        if not path.startswith("/api/"):
            return await call_next(request)

        # Shared-secret gate — only when a secret is configured, and only for
        # paths not in the read-only bypass set.
        secret = _shared_secret()
        if secret and path not in _BYPASS_PATHS:
            provided = request.headers.get(SHARED_SECRET_HEADER, "")
            # Constant-time compare — avoids leaking the secret via response timing.
            if not hmac.compare_digest(provided, secret):
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": (
                            "Missing or invalid shared secret. "
                            "Set the X-RST-Gateway-Token header to the value of "
                            "RST_GATEWAY_SHARED_SECRET on the gateway."
                        ),
                    },
                )

        # SSO enforcement — when RST_SSO_ENFORCE is on, every gated /api/* call
        # must carry a verified identity from the forward-auth proxy. This is
        # checked independently of the shared secret so it is NOT short-circuited
        # by the no-secret path: an anonymous request must still be rejected.
        # Health + license endpoints stay reachable so the gateway can boot and
        # a lapsed license can be re-activated before any identity exists.
        if (
            _sso_enforced()
            and path not in _ENFORCE_EXEMPT_PATHS
            and sso_user_from_request(request) is None
        ):
            return JSONResponse(
                status_code=401,
                content=error_payload("sso_identity_required"),
            )

        # Password login — when RST_ADMIN_PASSWORD_HASH is configured, a gated
        # /api/* call must carry a valid session cookie. Checked independently
        # of the shared secret for the same reason SSO enforcement is: the
        # shared secret authenticates the proxy chain, this authenticates the
        # human, and passing one must not stand in for the other.
        if (
            login_enabled()
            and path not in _LOGIN_EXEMPT_PATHS
            and not session_valid(request)
            and not _has_admin_token(request)
        ):
            return JSONResponse(
                status_code=401,
                content=error_payload("login_required"),
            )

        # Read-only role gate. Deliberately by HTTP method rather than by
        # decorating each mutating route: there are 49 of them, hanging a guard
        # on every one is a checklist that only has to be missed once, and the
        # next route somebody adds would default to unguarded. By method the
        # default is safe and new routes inherit it.
        if (
            request.method.upper() not in _SAFE_METHODS
            and path not in _WRITE_EXEMPT_PATHS
            and not path.startswith(_WRITE_EXEMPT_PREFIXES)
            and path not in _READ_ONLY_POST_PATHS
            and effective_role(request) == "viewer"
        ):
            return JSONResponse(
                status_code=403,
                content=error_payload("read_only"),
            )
        return await call_next(request)


def is_admin(request: Request) -> bool:
    """Return True if this request is entitled to admin operations.

    There are exactly two deployment shapes, because `login_enabled()` is
    defined as `not sso_enabled()`:

      * SSO on  — RBAC only. The user must be in one of RST_RBAC_ADMIN_GROUPS.
        The ops token is NOT honored: an SSO deployment has committed to
        identity-based auth, and a static shared token is the opposite of that.
      * SSO off — password login. A valid session, or the ops token for callers
        that cannot hold a cookie (curl / CI).

    Three further branches used to follow — shared secret grants admin, ops
    token grants admin, unconfigured demo grants admin. They were unreachable:
    every path through the two cases above returns first. The security review
    read them as live policy and filed "shared secret is equivalent to admin"
    as a finding, which is the real cost of dead code inside an authorization
    function. Deleted rather than annotated, so the next reader sees the rule
    that is actually enforced.

    What the shared secret does is unchanged and is a different question:
    SharedSecretMiddleware decides whether a request may be *made at all*. It
    authenticates the proxy chain. It does not say who is calling — and it no
    longer looks like it does.
    """
    return effective_role(request) == "admin"


def effective_role(request: Request) -> str | None:
    """The live role behind this request: "admin", "analyst", "viewer", or None.

    None means "no role opinion" — an unauthenticated request, or one of the two
    identity shapes that carry no role (the ops token under SSO, a
    trusted-proxy-header user with no matching account). It is not a role and
    must never be treated as one; every check here asks for a specific role.

    Live is the important word. The session record carries the role it was
    issued with, and reading *that* would mean a demotion or a suspension sat
    dormant until the session expired. The role comes from `user_db` on every
    request instead; it is a dict lookup off a cached table, not a query.
    """
    if not sso_enabled() and _has_admin_token(request):
        # Ops token: machine callers (curl / CI) that cannot hold a cookie.
        # Still refused under SSO — that deployment committed to identity-based
        # auth, and a static shared token is the opposite of that.
        return "admin"
    user = current_user(request)
    if not user:
        return None
    if user.get("source") == "sso":
        return _role_from_groups([str(g) for g in (user.get("roles") or [])])
    # Password session, or a trusted-proxy-header identity. Both name an
    # account; only accounts in the user table have a role. A header identity
    # that matches no account keeps the pre-role behaviour (authenticated,
    # unrestricted apart from the admin checks), which is what that mode did
    # before roles existed.
    from . import user_db

    return user_db.role_of(str(user.get("username") or ""))


def require_admin(request: Request) -> None:
    """Guard for security-sensitive mutating endpoints. Raises 403 with a
    deployment-mode-specific message when is_admin() is False."""
    if is_admin(request):
        return

    # Signed in, just not an administrator. Worth its own message: the other
    # branches all say some variant of "log in", which is wrong advice for
    # somebody who is already logged in and would send them round the login
    # page looking for a permission it cannot give them.
    role = effective_role(request)
    if role in ("analyst", "viewer"):
        raise ApiError("admin_role_required", 403, role=role)

    if sso_enabled():
        raise ApiError("admin_group_required", 403)
    if _admin_token():
        raise ApiError("admin_session_or_token_required", 403)
    raise ApiError("admin_login_required", 403)


def client_ip_from_request(request: Request) -> str | None:
    """Best-effort client IP for audit / observability.

    Mirrors RateLimitMiddleware._client_ip: the RIGHTMOST X-Forwarded-For entry
    (the hop appended by the immediate trusted proxy, e.g. Caddy) so a
    client-supplied leftmost value cannot forge it; falls back to the TCP peer.
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    if request.client:
        return request.client.host
    return None


# ─────────────────────── SSO (forward-auth) identity ───────────────────────
#
# A forward-auth proxy (oauth2-proxy / Authelia / a SAML proxy) authenticates
# the user against the customer's IdP and injects the verified identity as
# request headers. The gateway trusts these headers because:
#   1. The proxy OVERWRITES them from the verified session — a client cannot
#      smuggle its own value through the proxy.
#   2. The gateway is only reachable via the proxy chain; SharedSecretMiddleware
#      rejects any /api/* request that did not carry the shared secret.
# Header names default to oauth2-proxy's `--set-xauthrequest` set; override via
# RST_SSO_USER_HEADER / RST_SSO_GROUPS_HEADER for a proxy that names them
# differently.

# Identity header candidates, checked in order. oauth2-proxy's
# --set-xauthrequest emits X-Auth-Request-*; --pass-user-headers emits
# X-Forwarded-*. Other proxies differ — prepend yours via RST_SSO_USER_HEADER
# / RST_SSO_GROUPS_HEADER.
_SSO_USER_HEADERS = [h for h in [
    os.environ.get("RST_SSO_USER_HEADER", "").strip().lower(),
    "x-auth-request-email", "x-forwarded-email",
    "x-auth-request-user", "x-forwarded-user",
] if h]
_SSO_GROUPS_HEADERS = [h for h in [
    os.environ.get("RST_SSO_GROUPS_HEADER", "").strip().lower(),
    "x-auth-request-groups", "x-forwarded-groups",
] if h]


def sso_enabled() -> bool:
    """True when the deployment is fronted by an SSO forward-auth proxy."""
    return os.environ.get("RST_SSO_ENABLED", "").strip().lower() in ("1", "true", "yes")


def _sso_enforced() -> bool:
    """True when gated /api/* calls must carry a verified SSO identity."""
    return os.environ.get("RST_SSO_ENFORCE", "").strip().lower() in ("1", "true", "yes")


def _identity_trusted() -> bool:
    """Whether the forward-auth identity headers (X-Auth-Request-*) may be trusted.

    They are injected by the forward-auth proxy and are trustworthy ONLY when the
    gateway is reachable solely via that proxy chain — which we can only assume
    when a shared secret is configured (SharedSecretMiddleware then rejects any
    direct /api/* call). With SSO enabled but NO shared secret, any direct client
    could forge `X-Auth-Request-Groups` (fake admin) / `X-Auth-Request-Email`
    (impersonate a user), so we refuse to trust the headers and fall back to
    anonymous / non-admin.

    SSO disabled (demo / Basic-Auth) → identity headers are never consulted
    anyway (sso_user_from_request returns None), so this gate is a no-op there
    and demo-mode behaviour is unchanged.
    """
    return sso_enabled() and bool(_shared_secret())


def sso_user_from_request(request: Request) -> dict[str, object] | None:
    """Verified end-user identity from the forward-auth proxy headers, or None.

    Returns None unless the identity headers are trustworthy (see
    _identity_trusted) — otherwise a direct caller could spoof identity/groups.
    """
    if not _identity_trusted():
        return None
    name = ""
    for h in _SSO_USER_HEADERS:
        name = request.headers.get(h, "").strip()
        if name:
            break
    if not name:
        return None
    groups: list[str] = []
    for h in _SSO_GROUPS_HEADERS:
        raw = request.headers.get(h, "").strip()
        if raw:
            groups = [g.strip() for g in raw.split(",") if g.strip()]
            break
    return {"username": name, "roles": groups, "source": "sso"}


def _trusted_user_header() -> str:
    """Optional non-SSO per-user identity header name (lowercased).

    Lets a deployment that is NOT running full SSO/RBAC but IS fronted by an
    authenticating reverse proxy still attribute per-user state (history / saved
    queries / prefs). Without it, non-SSO analysts all share the `_shared` bucket.
    """
    return os.environ.get("RST_TRUSTED_USER_HEADER", "").strip().lower()


def current_user(request: Request) -> dict[str, object] | None:
    """End-user identity for audit / display.

    Primary source is the SSO forward-auth proxy. As a fallback, an operator may
    set RST_TRUSTED_USER_HEADER to name a username header their reverse proxy
    injects; it is honored ONLY when a shared secret is configured (so the gateway
    is reachable solely via that proxy chain and the header can't be forged) — the
    same trust basis as the SSO headers. Without either, None is returned, which
    is accurate: there is no authenticated per-user identity to attribute.

    Last comes the password session. Until now this function returned None in
    that mode, which is why audit records went out with no user at all and why
    every analyst's history, prefs and saved queries landed in one `_shared`
    bucket. Nothing else in the backend consumes identity — this is the single
    point all thirty call sites go through — so teaching it about password
    sessions is what makes the rest of the product multi-user aware.

    Existing single-user deployments keep their data: see the shared-bucket
    fallback in `user_state`.

    The legacy, spoofable `X-Kibana-User` path was removed (Kibana plugin track
    abandoned 2026-04-30).
    """
    user = sso_user_from_request(request)
    if user:
        return user
    header = _trusted_user_header()
    if header and _shared_secret():
        name = request.headers.get(header, "").strip()
        if name:
            return {"username": name, "roles": [], "source": "proxy-header"}
    return session_identity(request)


# ─────────────────────────── RBAC (group → role) ───────────────────────────
#
# An SSO deployment has no user table — the IdP owns the accounts, and the only
# thing that reaches us is a list of group names. So the three roles are mapped
# from groups, one environment variable per role, all in the shape
# RST_RBAC_ADMIN_GROUPS already had. A user in several mapped groups gets the
# highest of them.
#
# Honored ONLY when SSO is enabled — the identity headers are trustworthy only
# behind a forward-auth proxy (otherwise a client could forge the group header).
#
# An SSO user in none of the mapped groups gets None, not viewer. Defaulting
# them to read-only would silently take write access away from every existing
# SSO deployment the day it upgrades, because none of them has set the two new
# variables. A deployment that wants read-only enforcement names the group in
# RST_RBAC_VIEWER_GROUPS, which is an act, not an accident.

_ROLE_GROUP_VARS = (
    ("admin", "RST_RBAC_ADMIN_GROUPS"),
    ("analyst", "RST_RBAC_ANALYST_GROUPS"),
    ("viewer", "RST_RBAC_VIEWER_GROUPS"),
)


def _rbac_groups(var: str) -> set[str]:
    return {g.strip() for g in os.environ.get(var, "").split(",") if g.strip()}


def _role_from_groups(groups: list[str]) -> str | None:
    """Highest role any of `groups` maps to, or None if none of them map."""
    for role, var in _ROLE_GROUP_VARS:
        if groups and _rbac_groups(var) & set(groups):
            return role
    return None
