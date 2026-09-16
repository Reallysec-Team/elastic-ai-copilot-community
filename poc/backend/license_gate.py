"""License gate middleware.

Routes are categorized as:
  ALWAYS_ALLOW         /healthz, /readyz, /api/license/*, static files
  GATED_GENERATIVE     /api/generate, /api/execute  (apply unactivated quota)
  GATED_LIGHTWEIGHT    /api/feedback, /api/kibana-link  (no quota; just block on hard-fail)

Behavior matrix (matches reference_rst_platform_license decision #3):

  status               generative          lightweight       always-allow
  ─────────────────────────────────────────────────────────────────────
  unactivated          quota gate          allowed           allowed
  valid / expiring     allowed             allowed           allowed
  grace                allowed             allowed           allowed
  expired / heartbeat
  _lost / invalid /
  revoked              403                 403               allowed
"""

from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import license_state as ls
from .api_errors import error_payload

_ALWAYS_ALLOW = {
    "/healthz",
    "/readyz",
    "/api/me",
    "/api/license/status",
    "/api/license/activate",
    "/api/license/server-guid",
    "/api/license/host-fingerprint",
    "/api/license/reload",
    "/api/license/deactivate",
    "/api/license/quota",
    "/api/masking/info",
    "/api/llm/providers",
    "/api/llm/providers/save",
    "/api/llm/reload",
    "/api/indices",
    "/api/settings",
    "/api/engines",
}
# `/api/kb/` is deliberately NOT here — RAG endpoints call the LLM, so they must
# be blocked when the license is in a hard-fail state. They fall through to the
# gate below (hard-fail → 403; otherwise allowed, no quota).
# `/api/state/` (per-owner UI state: triage sync, history, prefs, saved queries)
# is non-generative — a lapsed license should NOT cut team triage sync, so it
# bypasses the gate like the other lightweight read/write surfaces.
# 不带尾斜杠，匹配时按「路径等于它，或者是它的子路径」判。
# 原来是裸的 startswith，而元组里 `/api/dashboards` 和 `/api/admin/content` 漏了
# 尾斜杠、其余四条都带着 —— 是笔误不是设计。后果是任何以这串字符开头的
# 新路由（`/api/dashboards-export`、`/api/admin/content-generate`）会自动绕过
# license 闸，包括 hard-fail 的 403。又不能单纯改成带斜杠：`/api/dashboards`
# 本身就是一条真路由（main.py:2471），那样会把它挤出白名单。
_ALWAYS_ALLOW_PREFIXES = (
    # 登录 / 登出 / 改密码不能被许可闸挡：证失效（换机器、被撤、过期）时管理员
    # 得先登得进来才能到许可页贴新证或反激活。2026-09-14 离线演练里 state 卷
    # 拷到另一台机器，登录直接 403 license_invalid，只能改卷。
    "/api/auth",
    "/api/conversations",
    "/api/feedback",
    "/api/audit",
    "/api/dashboards",
    "/api/reports",
    "/api/state",
    "/api/admin/content",
)


def _always_allowed_prefix(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in _ALWAYS_ALLOW_PREFIXES)
# 扣额度的那一类路由不再在这里手工枚举 —— 由路由自己用 `@llm_post(...)` 声明
# （见 llm_cost.py）。惰性读：路由是在 main.py 导入时登记的，而这里的 dispatch
# 只在请求时才问。
def _gated_generative() -> frozenset[str]:
    from . import llm_cost

    return llm_cost.generative()


_GATED_LIGHTWEIGHT = {"/api/kibana-link", "/api/feedback", "/api/field-dict", "/api/conversations"}

_HARD_FAIL_STATES = {
    ls.STATUS_INVALID,
    ls.STATUS_EXPIRED,
    ls.STATUS_REVOKED,
    ls.STATUS_HEARTBEAT_LOST,
}


class LicenseGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path

        gated = _gated_generative()

        # static files / unknown paths / always-allow → passthrough.
        # 一条会调 LLM 的路由压过前缀白名单：`/api/reports/generate` 就落在
        # `/api/reports` 这个前缀下面，照原来的顺序它连 hard-fail 都绕过去了。
        if path not in gated and (
            path in _ALWAYS_ALLOW
            or _always_allowed_prefix(path)
            or not path.startswith("/api")
        ):
            return await call_next(request)

        status = ls.get_state()["status"]

        if status in _HARD_FAIL_STATES:
            return JSONResponse(
                status_code=403,
                content={**error_payload(_code_for(status)), "license_status": status},
            )

        if path in gated:
            if status == ls.STATUS_UNACTIVATED:
                allowed = await ls.consume_unactivated_quota()
                if not allowed:
                    return JSONResponse(
                        status_code=402,
                        content={
                            **error_payload(
                                "trial_quota_exhausted", limit=ls.TRIAL_DAILY_LIMIT
                            ),
                            "license_status": status,
                        },
                    )
                response = await call_next(request)
                # A sealed feature refusing the call (403) never reached the
                # model; give the trial call back. LLM failures refund
                # themselves inside the handler, so only 403 is handled here.
                if getattr(response, "status_code", None) == 403:
                    await ls.refund_unactivated_quota()
                return response
            return await call_next(request)

        if path in _GATED_LIGHTWEIGHT:
            return await call_next(request)

        # Any other /api/* falls through (no future endpoint should hit here yet)
        return await call_next(request)


# 整个产品被锁住时，这是操作者看到的唯一一句话 —— 它必须带错误码，否则英文界面
# 只能原样显示中文 detail。文案本身在 api_errors.MESSAGES 里（中文唯一真源），
# 一个字没变。
_CODE_BY_STATUS = {
    ls.STATUS_INVALID: "license_invalid",
    ls.STATUS_EXPIRED: "license_expired",
    ls.STATUS_REVOKED: "license_revoked",
    ls.STATUS_HEARTBEAT_LOST: "license_heartbeat_lost",
}


def _code_for(status: str) -> str:
    return _CODE_BY_STATUS.get(status, "license_status_abnormal")
