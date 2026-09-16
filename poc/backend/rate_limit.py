"""Per-IP token-bucket rate limiter — process-local, no external deps.

Buckets — per-minute limits are operator-tunable via env (defaults shown):
  /api/generate            — RST_RATELIMIT_GENERATE        (default 30 req/min/IP)
  /api/generate/stream     — shares the /api/generate bucket (can't be bypassed)
  /api/investigate-alert/stream — shares the /api/investigate-alert bucket
  /api/execute             — RST_RATELIMIT_EXECUTE         (default 30 req/min/IP)
  /api/kibana-link         — RST_RATELIMIT_KIBANA_LINK     (default 120 req/min/IP)
  /api/explain-log         — RST_RATELIMIT_EXPLAIN_LOG     (default 30 req/min/IP)
  /api/investigate-alert   — RST_RATELIMIT_INVESTIGATE     (default 30 req/min/IP)
  /api/detection-rule/generate — RST_RATELIMIT_DETECTION_RULE (default 30 req/min/IP)
  /api/triage/batch        — RST_RATELIMIT_TRIAGE_BATCH    (default 6 req/min/IP)
  /api/report/incident     — RST_RATELIMIT_REPORT_INCIDENT (default 6 req/min/IP)
  /api/explain-result      — RST_RATELIMIT_EXPLAIN_RESULT  (default 30 req/min/IP)
  /api/reports/generate    — RST_RATELIMIT_REPORTS_GENERATE (default 6 req/min/IP)
  /api/kb/search           — RST_RATELIMIT_KB_SEARCH       (default 60 req/min/IP)
  /api/platform/interpret  — RST_RATELIMIT_PLATFORM_INTERPRET (default 30 req/min/IP)
  /api/alerts/ingest       — RST_RATELIMIT_ALERT_INGEST     (default 120 req/min/IP)
  /healthz, /readyz        — unlimited
  others                   — passthrough (unlimited)

The expensive LLM endpoints are all covered so none is an un-throttled hole, and
/api/generate/stream is keyed onto the same bucket as /api/generate so switching
to the streaming variant can't be used to evade the generate limit. The batch /
incident endpoints fan out into many LLM calls per request, so they default to a
much stricter per-minute limit.

PoC scope. For multi-process or distributed limiting swap in Redis later.
"""

import logging
import math
import os
import threading
import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from .api_errors import error_payload

logger = logging.getLogger("rst.rate_limit")


def _bucket_from_env(env_var: str, default_rpm: float) -> tuple[float, float]:
    """Resolve a per-path limit. The env value is requests-per-minute; returns
    (capacity, refill_rate_per_second). Unset or invalid → the default."""
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return default_rpm, default_rpm / 60.0
    try:
        rpm = float(raw)
        if rpm <= 0:
            raise ValueError
    except ValueError:
        logger.warning(
            "invalid rate-limit env %s=%r — falling back to %s req/min",
            env_var, raw, default_rpm,
        )
        return default_rpm, default_rpm / 60.0
    return rpm, rpm / 60.0


# path → (env var, default req/min). Resolved lazily into `_BUCKETS` so an
# operator env change can be picked up via reload() without a restart (the eager
# import-time dict froze the limits for the process lifetime). Defaults match the
# prior hardcoded values, so an unconfigured deployment behaves exactly as before.
#
# 这张表现在由路由自己声明（`llm_cost.marker` / `@llm_post(... rpm=...)`），
# 这里只是把登记结果读出来 —— 手工枚举漏掉一条昂贵路由的老问题就没了。
def _bucket_spec() -> dict[str, tuple[str, float]]:
    from . import llm_cost

    return llm_cost.rate_limits()


# (capacity, refill rate per second) per path. Built on first access; cleared by
# reload() so settings._reset_dependents() can re-read the RST_RATELIMIT_* envs.
_BUCKETS: dict[str, tuple[float, float]] | None = None


def _buckets() -> dict[str, tuple[float, float]]:
    global _BUCKETS
    if _BUCKETS is None:
        _BUCKETS = {
            path: _bucket_from_env(env_var, default)
            for path, (env_var, default) in _bucket_spec().items()
        }
    return _BUCKETS


def reload() -> None:
    """Drop the cached buckets so the next request re-reads RST_RATELIMIT_* env.
    Wired into settings._reset_dependents() — limits become live-editable."""
    global _BUCKETS
    _BUCKETS = None


# Path aliases — requests to the key path are limited *as if* they hit the value
# path: same bucket config AND same counter state. /api/generate/stream shares
# /api/generate so a client can't dodge the generate limit by streaming instead.
_BUCKET_ALIAS: dict[str, str] = {
    "/api/generate/stream": "/api/generate",
    "/api/investigate-alert/stream": "/api/investigate-alert",
}

_UNLIMITED = {"/healthz", "/readyz"}

# Bucket housekeeping — without this, `_state` grows one entry per distinct
# (IP, path) forever (a memory-exhaustion vector when X-Forwarded-For is
# attacker-varied). A bucket untouched for `_IDLE_EVICT`s has fully refilled,
# so dropping it is behaviour-neutral — a fresh request rebuilds it identically.
_PRUNE_INTERVAL = 300.0
_IDLE_EVICT = 600.0


def _canonical_path(path: str) -> str:
    """Map a request path to the path whose bucket/counter it shares."""
    return _BUCKET_ALIAS.get(path, path)


def _resolve_bucket(path: str) -> tuple[float, float] | None:
    if path in _UNLIMITED:
        return None
    return _buckets().get(path)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        # key (ip, path) → [tokens, last_refill_monotonic]
        self._state: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()
        self._last_prune = 0.0

    async def dispatch(self, request: Request, call_next: Callable):
        # Canonicalise first so aliased paths (e.g. /api/generate/stream) share
        # both the bucket config and the counter state of their target.
        limit_path = _canonical_path(request.url.path)
        bucket = _resolve_bucket(limit_path)
        if bucket is None:
            return await call_next(request)

        capacity, refill_rate = bucket
        client_ip = self._client_ip(request)
        key = (client_ip, limit_path)
        now = time.monotonic()

        tokens_left = 0.0
        with self._lock:
            self._prune_locked(now)
            entry = self._state.get(key)
            if entry is None:
                self._state[key] = [capacity - 1.0, now]
                allowed = True
            else:
                tokens = min(capacity, entry[0] + (now - entry[1]) * refill_rate)
                if tokens >= 1.0:
                    entry[0] = tokens - 1.0
                    entry[1] = now
                    allowed = True
                else:
                    entry[0] = tokens
                    entry[1] = now
                    allowed = False
                    tokens_left = tokens

        if not allowed:
            # Seconds until one token refills, so the client (and the errorHelp
            # hint) can say how long to wait instead of guessing. Standard header.
            retry_after = 1 if refill_rate <= 0 else max(1, math.ceil((1.0 - tokens_left) / refill_rate))
            return JSONResponse(
                status_code=429,
                content=error_payload("rate_limited", seconds=retry_after),
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)

    def _prune_locked(self, now: float) -> None:
        """Drop fully-refilled idle buckets so `_state` cannot grow unbounded.
        Caller must hold `self._lock`."""
        if now - self._last_prune < _PRUNE_INTERVAL:
            return
        self._last_prune = now
        stale = [k for k, e in self._state.items() if now - e[1] > _IDLE_EVICT]
        for k in stale:
            del self._state[k]

    @staticmethod
    def _client_ip(request: Request) -> str:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            if parts:
                # Rightmost = the address appended by the immediate trusted
                # proxy (e.g. Caddy). Leftmost entries are client-supplied and
                # forgeable — keying limits on them lets a client rotate fake
                # IPs to evade the limit. Multi-proxy stacks: front the gateway
                # with a proxy that overwrites X-Forwarded-For.
                return parts[-1]
        if request.client:
            return request.client.host
        return "unknown"
