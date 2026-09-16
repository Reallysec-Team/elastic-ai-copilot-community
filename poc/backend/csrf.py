"""Origin check — CSRF defence in depth for the session cookie.

`SameSite=Lax` already blocks the cross-site POST that a forged form would
issue, so this is not the only thing standing between an attacker and the 23
`require_admin` endpoints. It is the layer that keeps holding when `Lax` stops
applying: a state-changing endpoint that grows a GET variant, a sibling
subdomain that counts as same-site, or a browser whose `Lax` default an
operator has turned off.

The rule is deliberately narrow:

  * Safe methods pass. GET/HEAD/OPTIONS must not be state-changing anyway, and
    gating them would break every ordinary page load.
  * A request with **no** `Origin` passes. Every browser attaches `Origin` to a
    cross-site state-changing request; curl, CI and the admin-token machine
    callers do not, and they carry no ambient cookie for an attacker to ride.
    Rejecting them would break automation to stop an attack that cannot happen.
  * An `Origin` whose host:port differs from the request's own `Host` is
    rejected, unless the operator named it in `RST_CORS_ORIGINS`.

Scheme is not compared. Behind a TLS-terminating proxy the gateway sees plain
HTTP while the browser reports `https://`, so requiring a scheme match would
reject every legitimate request in exactly the deployment shape this product
ships to.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from .api_errors import error_payload

logger = logging.getLogger("rst.csrf")

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def _netloc(origin: str) -> str:
    """host:port of an origin string, lowercased. '' when unparseable."""
    try:
        return urlsplit(origin.strip()).netloc.lower()
    except ValueError:
        return ""


def _allowed_netlocs(request: Request) -> set[str]:
    """Origins this gateway answers to: its own Host, plus operator-named ones.

    `RST_CORS_ORIGINS` already means "a genuinely separate front-end host"
    (see main.py), which is the same set of origins that may legitimately post
    here. Reusing it avoids a second env var that would drift out of sync.
    """
    allowed = {
        _netloc(o)
        for o in os.environ.get("RST_CORS_ORIGINS", "").split(",")
        if o.strip()
    }
    allowed.discard("")
    host = request.headers.get("host", "").strip().lower()
    if host:
        allowed.add(host)
    return allowed


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method.upper() in _SAFE_METHODS:
            return await call_next(request)

        origin = request.headers.get("origin", "").strip()
        # "null" is what a sandboxed iframe or a data: URL sends. It is never a
        # legitimate caller here, and it must not be treated as "absent".
        if not origin:
            return await call_next(request)

        if origin.lower() != "null" and _netloc(origin) in _allowed_netlocs(request):
            return await call_next(request)

        logger.warning(
            "csrf_origin_rejected — %s %s from origin=%r host=%r",
            request.method, request.url.path, origin,
            request.headers.get("host", ""),
        )
        return JSONResponse(
            status_code=403,
            content=error_payload("csrf_rejected"),
        )
