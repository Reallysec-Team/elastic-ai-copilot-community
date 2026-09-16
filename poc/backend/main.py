import asyncio
import json
import logging
import hmac
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import audit, feature_unlock
from . import index_router
from . import analysis_store
from . import backend_adapter
from . import metrics
from . import conversation
from . import response_cache
from . import dashboards as gw_dashboards
from . import user_state
from . import preflight
from . import report_scheduler
from . import ilm
from . import field_masking
from . import heartbeat
from . import index_whitelist, owned_indices
from . import license_state as ls
from . import embeddings
from . import rag
from . import llm_router
from . import llm_cost
from . import reports as gw_reports
from . import settings as gw_settings
from .baseline import scheduler as baseline_scheduler
from .baseline import store as baseline_store
from .baseline_routes import router as baseline_router
from .notify import config as notify_config
from .notify import outbox as notify_outbox
from .notify_routes import router as notify_router
from .alerts import ingest as alert_ingest
from .alerts_routes import router as alerts_router

# Overlay settings.yml onto os.environ before any module reads from env.
gw_settings.apply_overlay()
from .platform_ops_routes import router as platform_ops_router
from .rag_endpoints import router as rag_router
from . import corrections
from . import solutions
from .auth import (
    SharedSecretMiddleware,
    client_ip_from_request,
    current_user,
    effective_role,
    is_admin,
    require_admin,
    sso_enabled,
)
from . import session_auth, session_store, user_db
from .es_client import (
    get_es,
    build_client as build_es_client,
    close_es,
    es_api_error,
    execute_search,
    get_mapping,
    ping,
)
from .enrich import csv_import
from .enrich import probe as enrich_probe
from .explain import explain_log, explain_result
from . import suggest_angles
from .field_dict import get_field_dictionary, sample_values_for_prompt
from .detection_rule import generate_detection_rule
from . import agentic_investigate
from .csrf import OriginCheckMiddleware
from .investigate import investigate_alert
from .kibana_link import (
    DataViewNotFound,
    build_kibana_link,
    origin_ignored as trusted_origin_ignored,
    trusted_origin,
)
from .license_gate import LicenseGateMiddleware
from .license_verifier import InvalidLicense
from rstlic_features import FeatureLocked  # flat import — see backend/__init__.py
from .llm import generate_dsl, generate_dsl_stream
from .logging_config import configure_logging
from .prompts import prompt_version
from . import content_store
from . import release_store
from .rstlic_verifier import LicenseError
from .rate_limit import RateLimitMiddleware
from .incident_report import generate_incident_report
from .api_errors import ApiError, error_body
from .schemas import (
    AppliedTimeWindow,
    ActivateRequest,
    DetectionRuleRequest,
    ExecuteRequest,
    ExplainLogRequest,
    ExplainResultRequest,
    SuggestAnglesRequest,
    FeedbackRequest,
    FieldDictRequest,
    GenerateRequest,
    GenerateResponse,
    IndexRouting,
    IncidentReportRequest,
    InvestigateRequest,
    KibanaLinkRequest,
    LLMProvidersSaveRequest,
    LoginRequest,
    PasswordChangeRequest,
    UserCreateRequest,
    UserUpdateRequest,
    EmbeddingSaveRequest,
    EmbeddingTestRequest,
    ReportRequest,
    TriageBatchRequest,
)
from .server_guid import get_server_guid, get_host_fingerprint
from .triage import triage_alerts
from . import time_window
from .validator import apply_default_sort, validate_dsl
from fastapi import Request


configure_logging()
logger = logging.getLogger("rst.api")

_FAILED_CASES_PATH = Path(__file__).parent.parent / "eval" / "failed_cases.yaml"
_FAILED_CASES_LOCK = asyncio.Lock()


async def bootstrap_es_dependents() -> None:
    """Everything that has to run once the gateway has a working ES connection.

    Called at startup and again after the admin re-points the gateway at another
    cluster from the settings UI — otherwise a customer who finishes the setup
    wizard gets an empty rule library and no enrichment until someone restarts
    the container, which defeats the point of configuring it from the browser.

    Every step is best-effort and logged: ES being unreachable is the normal
    state of a fresh install that has not been configured yet, and must not stop
    the gateway from serving the very page used to configure it.
    """
    # Production-readiness preflight (SSO posture + ES write permission). Loud
    # warnings only — never blocks startup.
    try:
        await preflight.run()
    except Exception:  # noqa: BLE001
        logger.warning("preflight_failed", exc_info=True)
    # ILM retention bootstrap (off unless RST_ILM_BOOTSTRAP=1).
    try:
        # 上次跑着跑着挂了会留下永远 pending 的轮次；起来先收一遍。
        await conversation.reap_stale()
    except Exception:  # noqa: BLE001
        logger.warning("conversation_reap_failed", exc_info=True)
    try:
        await ilm.bootstrap()
    except Exception:  # noqa: BLE001
        logger.warning("ilm_bootstrap_error", exc_info=True)
    # Enrichment capability probe (which sources exist in the customer ELK).
    try:
        await enrich_probe.run(get_es())
    except Exception:  # noqa: BLE001
        logger.warning("enrichment_probe_failed", exc_info=True)
    # Install the shipped compliance pack on a fresh deployment. The rules ride
    # in the image but nothing loaded them into ES — that was a manual script —
    # so the baseline page opened on an empty rule library and read as broken.
    # Seeds ONLY an empty library, so a curated one is never regrown.
    try:
        n = await baseline_store.seed_bundled_rules_if_empty()
        if n:
            logger.info("baseline_rules_seeded", extra={"count": n})
    except Exception:  # noqa: BLE001 — never block startup
        logger.warning("baseline_seed_failed", exc_info=True)
    # 存量投递目标里的明文 webhook_url 换成密文。幂等，走和其它写一样的 CAS，
    # 所以和管理员同时在界面上保存不会互相盖掉；冲突了下次启动再来。
    try:
        n = await notify_config.migrate_plaintext_webhook_urls()
        if n:
            logger.warning("webhook_urls_encrypted", extra={"count": n})
    except Exception:  # noqa: BLE001 — never block startup
        logger.warning("webhook_url_migration_failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # License subsystem bootstrap — defensive: a license failure must degrade to
    # invalid/unactivated (handled by ls internals), never crash the gateway.
    try:
        get_server_guid()
    except Exception:  # noqa: BLE001
        logger.warning("server_guid_failed", exc_info=True)
    try:
        await ls.initial_load()
    except Exception:  # noqa: BLE001
        logger.exception("license_initial_load_failed")
    heartbeat.start()
    # User table: create it and seed the first administrator from the
    # environment. No-op without RST_USER_DB_URL. A failure here (database not
    # up yet) must not take the gateway down: /healthz and the license
    # endpoints stay reachable so the operator can see what is wrong. Logins
    # fail while the database is unreachable, which is the safe direction —
    # the alternative is a gateway that decides everyone is an admin.
    try:
        user_db.init()
    except Exception:  # noqa: BLE001
        logger.warning("user_db_init_failed", exc_info=True)
    await bootstrap_es_dependents()
    # Automated daily/weekly/monthly report patrol (off unless RST_REPORT_SCHEDULE set).
    report_scheduler.start()
    # Security-baseline inspection polling (off unless RST_BASELINE_INTERVAL_SECONDS set).
    baseline_scheduler.start()
    # Feishu delivery outbox worker (drains report/alert deliveries with retry).
    notify_outbox.start()
    # Real-time alert ingest tail — source A (off unless RST_ALERT_INGEST_INDEX set).
    alert_ingest.start()
    yield
    await alert_ingest.stop()
    await notify_outbox.stop()
    await baseline_scheduler.stop()
    await report_scheduler.stop()
    await heartbeat.stop()
    await close_es()


app = FastAPI(title="RST Elastic AI Copilot — PoC", lifespan=lifespan)

# 会花掉一次 LLM 调用的路由用 @llm_post 而不是 @app.post 声明：额度闸和限流桶
# 都从这份登记读（见 llm_cost.py），不再靠两张手工维护的枚举表。
llm_post = llm_cost.marker(app)


@app.exception_handler(ApiError)
async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    """把错误码和参数带进响应体。

    不装这个 handler 的话 FastAPI 会按普通 HTTPException 处理，只回 detail ——
    错误码原地丢失，前端又只剩中文可显示。
    """
    return JSONResponse(
        status_code=exc.status_code, content=error_body(exc), headers=exc.headers
    )


@app.exception_handler(FeatureLocked)
async def _feature_locked_handler(request: Request, exc: FeatureLocked) -> JSONResponse:
    """SEC-CC-1：密封引擎在这台机器上解不开 —— 许可没这项、绑在别的机器上、
    或者没有 keyring。四个付费能力（分级、调查、检测规则、功能管理）都从
    `feature_unlock.load_premium()` 拿引擎，都可能在任意深度抛出这个异常；
    一处兜住，比在每条路由里各写一遍 try/except 少漏。

    Fail SAFE：这项能力关掉，产品其余部分照常。
    """
    logger.warning(
        "premium_feature_locked",
        extra={"path": request.url.path, "error": str(exc)},
    )
    # rstlic phrases it as "'<feature>' locked: ..." — lift the id for the message.
    m = re.match(r"'([a-z_]+)' locked", str(exc))
    err = ApiError("feature_sealed", 403, feature=m.group(1) if m else "premium feature")
    return JSONResponse(status_code=403, content=error_body(err))

# Middleware execution order (CORS outermost → handler):
#   request → CORS → OriginCheck → RateLimit → SharedSecret → LicenseGate → handler
# add_middleware inserts at position 0, so add inner-first.
#
# OriginCheck sits outside RateLimit so a cross-site flood is rejected before it
# can spend the operator's own per-IP budget.
app.add_middleware(LicenseGateMiddleware)
app.add_middleware(SharedSecretMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(OriginCheckMiddleware)
# CORS: default deny. The SPA is served by this gateway and dev goes through
# Vite's proxy, so both are same-origin and need no CORS at all — `*` was
# granting every site on the internet read access to responses this gateway
# produces. Set RST_CORS_ORIGINS (comma-separated) only for a genuinely
# separate front-end host.
#
# Credentials stay off: with the session cookie now carrying auth, allowing
# them alongside a wildcard would be the difference between "another site can
# call the API anonymously" and "another site can call it AS the logged-in
# operator".
_cors_origins = [o.strip() for o in os.environ.get("RST_CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    if "*" in _cors_origins:
        logger.warning(
            "cors_wildcard — RST_CORS_ORIGINS contains '*', so any site can read "
            "this gateway's responses. Name the front-end origins instead."
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )


# ─────────────────────────── Metrics (P1-A) ───────────────────────────
# Prometheus scrape target. The middleware records request count + latency
# keyed on the matched route TEMPLATE (not the raw path) so id-bearing URLs
# like /api/conversations/{id} don't blow up label cardinality.


@app.middleware("http")
async def _record_metrics(request: Request, call_next):
    start = time.perf_counter()
    # Stash the client IP so audit events — written as fire-and-forget tasks
    # that inherit this context — can record who/where.
    audit.set_request_ip(client_ip_from_request(request))
    # A handler raising a bare (non-HTTP) exception would otherwise skip the
    # counters below, so unhandled 500s never appear in rst_http_requests_total
    # {status=~"5.."} — the exact series operators alert on. Record a 500 for the
    # raising path, then re-raise so the framework still returns its 500 response.
    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        route = request.scope.get("route")
        path = getattr(route, "path", None) or "<unmatched>"
        if path != "/metrics":
            metrics.http_requests.labels(request.method, path, "500").inc()
            metrics.http_latency.labels(request.method, path).observe(
                time.perf_counter() - start
            )
        raise
    route = request.scope.get("route")
    path = getattr(route, "path", None) or "<unmatched>"
    if path != "/metrics":  # don't self-instrument the scrape
        metrics.http_requests.labels(
            request.method, path, str(status_code)
        ).inc()
        metrics.http_latency.labels(request.method, path).observe(
            time.perf_counter() - start
        )
    return response


def _metrics_scrape_allowed(request: Request) -> bool:
    """未配 RST_METRICS_TOKEN 时一律放行（保持既有行为）；配了就必须带对。"""
    token = os.environ.get("RST_METRICS_TOKEN", "").strip()
    if not token:
        return True
    provided = request.headers.get("x-rst-metrics-token", "")
    if not provided:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            provided = auth_header[7:].strip()
    if hmac.compare_digest(provided, token):
        return True
    admin = os.environ.get("RST_ADMIN_TOKEN", "").strip()
    return bool(admin) and hmac.compare_digest(
        request.headers.get("X-RST-Admin-Token", ""), admin
    )


@app.get("/metrics")
def metrics_endpoint(request: Request):
    """Prometheus scrape endpoint.

    不在 /api/* 下面，所以共享密钥闸和登录闸都不管它 —— 客户的 Prometheus 在内网
    直接抓。这在有 Caddy 挡在前面的部署上没问题，但本产品也发不挂 Caddy 的局域网
    形态，那时它就是个谁都能读的口子（路由使用量 + license 状态）。

    设了 RST_METRICS_TOKEN 就要求带上（`Authorization: Bearer <token>` 或
    `X-RST-Metrics-Token`），RST_ADMIN_TOKEN 同样认 —— 运维手上本来就有它。
    两个都不设时维持原状：Prometheus 的配置不用改，升级不会突然抓不到。
    """
    if not _metrics_scrape_allowed(request):
        # 抓取端是 Prometheus，不是人：401 不带 WWW-Authenticate 的话，客户端只知道
        # 被拒了、不知道该带什么。正文里的中文是给翻日志的运维看的。
        raise ApiError(
            "metrics_token_required", 401,
            headers={"WWW-Authenticate": 'Bearer realm="rst-metrics"'},
        )
    status = ls.get_state().get("status")
    metrics.license_usable.set(
        1.0 if status in (ls.STATUS_VALID, ls.STATUS_EXPIRING, ls.STATUS_GRACE)
        else 0.0
    )
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ─────────────────────────── Helpers ───────────────────────────


def _feature_allowed(feature: str) -> bool:
    """See license_state.feature_allowed — kept as a local name because a dozen
    handlers below call it, and because tests monkeypatch main._feature_allowed."""
    return ls.feature_allowed(feature)


async def _index_candidates() -> list[index_router.Candidate]:
    """路由用的候选索引 —— 复用 /api/indices 的那套过滤（白名单、系统索引、
    产品自有索引）。拿不到就返回空，路由会退回「没有可查询的索引」。"""
    try:
        listing = await list_indices()
    except Exception as e:  # noqa: BLE001 - 路由失败不该让提问失败
        logger.info("index_candidates_failed", extra={"error": str(e)[:200]})
        return []
    return [
        index_router.Candidate(name=i["name"], doc_count=int(i.get("doc_count") or 0))
        for i in (listing.get("indices") or [])
    ]


async def _fill_profiles(candidates) -> None:
    """给候选补上「这是什么日志」。要读 mapping，所以只在模型那一步之前调一次，
    而且逐个 best-effort —— 一个索引读不到 mapping 不该拖垮整次路由。"""
    from .prompts import _flatten_mapping, index_profile

    for c in candidates[:12]:
        try:
            mapping = await get_mapping(c.name)
            c.profile = index_profile(_flatten_mapping(mapping))
        except Exception:  # noqa: BLE001
            continue


async def _load_prior_turns(conv_id: str | None, owner: str | None) -> tuple[list[dict], str | None]:
    """(prior_turns, conv_id)。过期 / 不是自己的会话 id 当没有，从头开始。"""
    if not conv_id:
        return [], None
    existing = await conversation.get(conv_id, owner=owner)
    if not existing:
        return [], None
    return conversation.turns_for_prompt(existing["turns"]), conv_id


async def _resolve_index(
    req_index: str, question: str, prior_turns: list[dict] | None = None,
) -> tuple[str, index_router.RoutingResult]:
    """用户给了索引就用他的；同一会话里追问就沿用上一轮的；都没有才按问题挑。

    追问沿用上一轮：冷启动验收里「只看第一名那个 IP，按小时统计」被路由到了
    nginx 错误日志，因为这句话本身没有任何线索 —— 线索在上一轮。要换索引的追问
    用户会点索引下拉，那走 given。

    返回 (index, routing)。路由结果要一路带回响应里显示出来。
    """
    given = (req_index or "").strip()
    if given:
        return given, index_router.RoutingResult(
            index=given, source="given", reason="按你指定的索引查", considered=[given]
        )
    last_index = next(
        (t.get("index") for t in reversed(prior_turns or []) if t.get("index")), None
    )
    if last_index:
        return last_index, index_router.RoutingResult(
            index=last_index, source="conversation", reason="追问沿用上一轮的索引",
            considered=[last_index],
        )

    candidates = await _index_candidates()
    routed = await index_router.route(
        question,
        candidates,
        chat=llm_router.get_router().chat_completion,  # noqa: E501
        profiles=_fill_profiles,
    )
    if not routed.index:
        raise ApiError("no_queryable_index")
    logger.info(
        "index_routed",
        extra={"source": routed.source, "index": routed.index[:200], "candidates": len(candidates)},
    )
    return routed.index, routed


def _check_index(index: str) -> None:
    """Reject requests targeting an index outside the configured whitelist,
    and — whitelist or not — anything that would reach the product's own
    storage (see index_whitelist.blocked_owned)."""
    owned = index_whitelist.blocked_owned(index)
    if owned:
        raise ApiError("index_is_internal", 403, index=owned)
    wl = index_whitelist.get()
    if not wl.is_allowed(index):
        raise ApiError("index_not_whitelisted", 403, index=index, patterns=wl.patterns())


# ─────────────────────────── /api/generate ───────────────────────────

# Someone rephrasing the same ask within a few minutes is telling us the first
# answer missed — a far more common signal than a thumbs-down, which nobody
# clicks. The window is short on purpose: two related questions ten minutes
# apart are an investigation, not a retry.
_REPEAT_WINDOW_S = 300
# Dice coefficient over character bigrams. Measured on real rephrasings:
#   登录失败的事件 / 哪些账号登录失败了      0.43
#   登录失败的事件 / 登录失败的账号有哪些    0.53
#   统计最近一小时 HTTP 500 / 最近一小时有多少 500 错误  0.48
# and on unrelated pairs (登录失败 vs 磁盘空间 / 5xx 统计): 0.00. The gap is
# wide, so sit near the bottom of it — a missed retry costs us a signal, a
# false one retires a good example.
_REPEAT_SIMILARITY = 0.35


async def _solution_examples(question: str, index: str, owner: str) -> list[dict]:
    """Worked examples for this question, and the repeat-ask failure signal.

    Best effort in both directions: the solutions store is an accelerator, and
    a question must still be answerable when it is empty, unreachable, or has
    no embedding model behind it.
    """
    try:
        await _flag_repeat_ask(question, index, owner)
    except Exception as e:  # noqa: BLE001
        logger.warning("repeat_ask_check_failed", extra={"error": str(e)[:200]})
    return await solutions.find_similar(question, index, top_k=3, owner=owner)


async def _flag_repeat_ask(question: str, index: str, owner: str) -> None:
    """Retire the earlier solution this question is a retry of, and file it as
    a failed case so the eval corpus learns from it."""
    for prior in await solutions.recent_questions(owner, within_s=_REPEAT_WINDOW_S):
        pq = prior.get("question") or ""
        if prior.get("rejected") or prior.get("index") != index or not pq:
            continue
        if solutions.cheap_similarity(question, pq) < _REPEAT_SIMILARITY:
            continue
        n = await solutions.reject_by_question(pq, index, owner, "repeat_ask")
        logger.info(
            "solution_repeat_ask",
            extra={"index": index, "user": owner, "retired": n},
        )
        await _append_failed_case({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "question": pq,
            "index": index,
            "dsl": None,
            "correct": False,
            "comment": f"用户在 {_REPEAT_WINDOW_S}s 内改口重问（新问题：{question[:200]}），"
                       "视为上一次没答对",
            "suggested_dsl": None,
            "prompt_version": prompt_version(),
            "dsl_was_edited": False,
            "signal": "repeat_ask",
        })
        return  # one retirement per ask is enough


def _capture_correction(question: str, index: str, prior_turns: list[dict], request: Request) -> None:
    """Turn "不对，转账失败要看 event_type=7" into a knowledge-base entry.

    Nobody opens the knowledge-base page to write Markdown, but people do
    correct an answer in passing — and that sentence is exactly the private
    convention the model had no way to know. Captured where it is actually
    said, which is mid-conversation.

    Admin-gated on purpose, matching /api/kb/upload: knowledge-base text is
    injected into every prompt and the system prompts tell the model to give
    it priority, so writing it is configuration-level power. In the
    single-operator deployments this ships to, the logged-in user IS the
    admin, so the gate costs nothing there while keeping an SSO deployment's
    analysts out of everyone's prompts.
    """
    if not prior_turns or not is_admin(request):
        return
    if not corrections.looks_like_correction(question):
        return  # free lexical gate — no LLM call for an ordinary question
    prior = prior_turns[-1]
    audit.fire_and_forget(corrections.capture(
        correction=question,
        owner=_conv_owner(request),
        question=prior.get("question"),
        index=index,
        dsl=prior.get("dsl"),
    ))


async def _append_failed_case(record: dict) -> None:
    """Append to the same YAML store /api/feedback writes, under its lock."""
    async with _FAILED_CASES_LOCK:
        data = _load_failed_cases()
        cases = data.setdefault("cases", [])
        cases.append(record)
        if len(cases) > _FAILED_CASES_MAX:
            del cases[: len(cases) - _FAILED_CASES_MAX]
        _atomic_write_yaml(data)


@llm_post("/api/generate", rpm_env="RST_RATELIMIT_GENERATE", rpm=30.0,
          response_model=GenerateResponse)
async def generate(req: GenerateRequest, request: Request, response: Response):
    start = time.perf_counter()
    conv_owner = _conv_owner(request)
    prior_turns, in_conv_id = await _load_prior_turns(req.conversation_id, conv_owner)
    resolved, routing = await _resolve_index(req.index, req.question, prior_turns)
    # 下游全部读 req.index（缓存键、mapping、样例、审计），改这一处比改十处安全。
    req = req.model_copy(update={"index": resolved})
    _check_index(req.index)
    user = current_user(request)

    try:
        mapping = await get_mapping(req.index)
    except Exception as e:
        raise es_api_error(e)

    # Real values for the enum-ish fields, so the model writes filters against
    # values that exist instead of guessing a literal. Best-effort and cached —
    # a failure here degrades to the old name+type prompt.
    field_samples = await sample_values_for_prompt(req.index)

    # Questions this deployment has already answered with a query that returned
    # data. Also where a rephrased retry retires the answer it is retrying.
    examples = await _solution_examples(req.question, req.index, conv_owner)
    _capture_correction(req.question, req.index, prior_turns, request)

    # Response cache — only for single-turn (prior context would change output).
    # Keyed on question+index+mapping fingerprint, so a mapping change invalidates.
    cache_key: str | None = None
    cached = None
    if not prior_turns:
        # prompt_version folds in the active content-pack version, so applying a
        # new prompt pack invalidates stale entries automatically (otherwise the
        # same question served the pre-pack DSL for up to the cache TTL). Provider/
        # model swaps are handled by clearing the cache in llm_router.
        cache_key = response_cache.make_key(
            "generate", req.question.strip(), req.index,
            response_cache.fingerprint(mapping),
            # Sample values are part of the prompt now, and they move without the
            # mapping moving — fold them in or a cached answer outlives its input.
            response_cache.fingerprint(field_samples),
            # Examples move independently of the mapping too — a new worked
            # example should not be shadowed by an answer generated without it.
            response_cache.fingerprint(examples),
            prompt_version(),
        )
        cached = response_cache.get(cache_key)

    # The license gate consumed an unactivated-trial unit BEFORE this handler ran
    # (it can't see what we do here). Refund it when no LLM call actually happens —
    # a cache hit or a generation failure — so the daily quota tracks real LLM use
    # and a failed/cached call doesn't permanently burn a unit (the stream path
    # already refunds on failure; this brings the non-stream path in line).
    is_unactivated = ls.get_state().get("status") == ls.STATUS_UNACTIVATED
    # 问题一到就落轮次（pending）；会话不存在就连会话一起建。
    out_conv_id, turn_id = await conversation.open_turn(
        in_conv_id, {"question": req.question, "index": req.index}, owner=conv_owner,
    )
    if cached is not None:
        # 缓存里可能是加 time_intent 之前存的四元组 —— 那时的条目当作「问题里没说
        # 时间」，退回筛选器优先，与加这个字段之前的行为一致。
        dsl, explanation, confidence, confidence_reason, *rest = cached
        time_intent = rest[0] if rest else None
        response.headers["X-Cache"] = "hit"
        if is_unactivated:
            await ls.refund_unactivated_quota()
    else:
        try:
            dsl, explanation, confidence, confidence_reason, time_intent = await generate_dsl(
                req.question, req.index, mapping, prior_turns=prior_turns,
                field_samples=field_samples, examples=examples,
            )
        except Exception as e:
            if is_unactivated:
                await ls.refund_unactivated_quota()
            await conversation.settle_turn(
                out_conv_id, turn_id, conversation.TURN_FAILED,
                {"error": {"code": "llm_generation_failed", "message": str(e)[:300]}},
                owner=conv_owner,
            )
            raise ApiError("llm_generation_failed", 500, reason=e)
        response.headers["X-Cache"] = "miss"
        if cache_key is not None and dsl is not None:
            response_cache.set(
                cache_key, (dsl, explanation, confidence, confidence_reason, time_intent),
            )

    if dsl is not None:
        try:
            validate_dsl(dsl)
        except Exception as e:
            await conversation.settle_turn(
                out_conv_id, turn_id, conversation.TURN_FAILED,
                {"error": {"code": "dsl_validation_failed", "message": str(e)[:300]}},
                owner=conv_owner,
            )
            raise ApiError("dsl_validation_failed", reason=e)

    # 这里也套一次（execute 还会再套一次，函数是幂等的）：用户在面板里看到的 DSL
    # 应该就是真正会跑的那一份，否则等于我们在背后改了他的查询。
    dsl, applied_window = await _apply_time_window(
        req.index, dsl, req.since, req.until, mapping=mapping, time_intent=time_intent,
    )

    await conversation.settle_turn(
        out_conv_id, turn_id, conversation.TURN_DONE,
        {"dsl": dsl, "explanation": explanation}, owner=conv_owner,
    )

    duration_ms = int((time.perf_counter() - start) * 1000)
    license_status = ls.get_state()["status"]
    logger.info(
        "generate",
        extra={
            "prompt_version": prompt_version(),
            "index": req.index,
            "question_len": len(req.question),
            "confidence": confidence,
            "dsl_is_null": dsl is None,
            "duration_ms": duration_ms,
            "license_status": license_status,
            "conversation_id": out_conv_id,
            "prior_turns_count": len(prior_turns),
            "user": user,
        },
    )
    audit.fire_and_forget(audit.write_event(
        "generate",
        index=req.index,
        user=user,
        license_status=license_status,
        prompt_version=prompt_version(),
        duration_ms=duration_ms,
        extra={
            "confidence": confidence,
            "dsl_is_null": dsl is None,
            "conversation_id": out_conv_id,
            "prior_turns_count": len(prior_turns),
        },
    ))
    return GenerateResponse(
        dsl=dsl,
        explanation=explanation,
        confidence=confidence,
        confidence_reason=confidence_reason,
        prompt_version=prompt_version(),
        conversation_id=out_conv_id,
        index=req.index,
        routing=IndexRouting(
            source=routing.source, reason=routing.reason, considered=routing.considered
        ),
        time_window=applied_window,
    )


# ─────────────────────────── /api/generate/stream (Round 7) ───────────────────────────


# 桶与 /api/generate 共用（见 rate_limit._BUCKET_ALIAS），所以这里不给自己的 rpm。
@llm_post("/api/generate/stream")
async def generate_stream(req: GenerateRequest, request: Request):
    """Streaming version of /api/generate — emits SSE frames.

    Frame types (each is one `data: <json>\\n\\n` block):
      {"type": "meta",  "conversation_id": "...", "prompt_version": "v3-..."}
      {"type": "chunk", "text": "<delta>", "provider": "ark-primary"}
      {"type": "done",  "dsl": {...}|null, "explanation": "...",
                        "confidence": "low|medium|high",
                        "confidence_reason": "..."|null,
                        "validation_error": "..."|null,
                        "duration_ms": 1234}
      {"type": "error", "message": "..."}

    The DSL is only validated AFTER the full response is parsed; clients
    should wait for "done" before treating the JSON as authoritative.
    """
    start = time.perf_counter()
    conv_owner = _conv_owner(request)
    prior_turns, in_conv_id = await _load_prior_turns(req.conversation_id, conv_owner)
    resolved, routing = await _resolve_index(req.index, req.question, prior_turns)
    req = req.model_copy(update={"index": resolved})
    _check_index(req.index)
    user = current_user(request)

    try:
        mapping = await get_mapping(req.index)
    except Exception as e:
        raise es_api_error(e)

    # Real values for the enum-ish fields, so the model writes filters against
    # values that exist instead of guessing a literal. Best-effort and cached —
    # a failure here degrades to the old name+type prompt.
    field_samples = await sample_values_for_prompt(req.index)

    examples = await _solution_examples(req.question, req.index, conv_owner)
    _capture_correction(req.question, req.index, prior_turns, request)

    # 问题一到就落轮次（pending）；会话不存在就连会话一起建。下面三个出口各自收尾：
    # done / error 帧 → done / failed；客户端断开或网关异常 → aborted / failed。
    out_conv_id, turn_id = await conversation.open_turn(
        in_conv_id, {"question": req.question, "index": req.index}, owner=conv_owner,
    )

    async def _settle(status: str, fields: dict | None = None) -> None:
        try:
            # shield：断开时这段是在 CancelledError 里跑的，不加会被第二次取消掐掉。
            await asyncio.shield(
                conversation.settle_turn(out_conv_id, turn_id, status, fields, owner=conv_owner)
            )
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001 — 收尾失败不能盖过真正的响应
            logger.warning("conversation_settle_failed", exc_info=True)

    async def event_stream():
        settled = False
        # Emit meta frame first so the client can show conversation/prompt-version
        # info even while the LLM is still warming up.
        yield _sse({
            "type": "meta",
            "conversation_id": out_conv_id,
            "prompt_version": prompt_version(),
            # 客户端拿这个去执行，并显示「在哪儿查的」。
            "index": req.index,
            "routing": {
                "source": routing.source,
                "reason": routing.reason,
                "considered": routing.considered,
            },
        })
        is_unactivated = ls.get_state().get("status") == ls.STATUS_UNACTIVATED
        stream_ok = False

        final_dsl: dict | None = None
        final_explanation = ""
        final_confidence = "medium"
        final_confidence_reason: str | None = None
        validation_error: str | None = None
        try:
            async for ev in generate_dsl_stream(
                req.question, req.index, mapping, prior_turns=prior_turns,
                field_samples=field_samples, examples=examples,
            ):
                if ev["type"] == "done":
                    stream_ok = True
                    final_dsl = ev.get("dsl")
                    final_explanation = ev.get("explanation", "")
                    final_confidence = ev.get("confidence", "medium")
                    final_confidence_reason = ev.get("confidence_reason")
                    final_usage = ev.get("usage")
                    final_output_chars = ev.get("output_chars")
                    if final_dsl is not None:
                        try:
                            validate_dsl(final_dsl)
                        except Exception as ve:  # noqa: BLE001
                            validation_error = str(ve)
                    # 界面选的时间范围：这里套一次，用户在面板里看到的就是真正
                    # 会跑的那份（execute 还会再套一次，函数幂等）。
                    final_dsl, applied_window = await _apply_time_window(
                        req.index, final_dsl, req.since, req.until, mapping=mapping,
                        time_intent=ev.get("time_intent"),
                    )
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    if final_dsl is not None and validation_error is None:
                        await _settle(conversation.TURN_DONE, {
                            "dsl": final_dsl, "explanation": final_explanation,
                        })
                    else:
                        await _settle(conversation.TURN_FAILED, {"error": {
                            "code": "dsl_validation_failed" if validation_error else "no_dsl",
                            "message": validation_error or final_explanation or "",
                        }})
                    settled = True
                    license_status = ls.get_state()["status"]
                    yield _sse({
                        "type": "done",
                        "dsl": final_dsl,
                        "explanation": final_explanation,
                        "confidence": final_confidence,
                        "confidence_reason": final_confidence_reason,
                        "validation_error": validation_error,
                        "duration_ms": duration_ms,
                        "output_chars": final_output_chars,
                        "usage": final_usage,
                        "conversation_id": out_conv_id,
                        "time_window": applied_window.model_dump() if applied_window else None,
                    })
                    audit.fire_and_forget(audit.write_event(
                        "generate",
                        index=req.index,
                        user=user,
                        license_status=license_status,
                        prompt_version=prompt_version(),
                        duration_ms=duration_ms,
                        outcome="success" if validation_error is None else "fail",
                        error=validation_error,
                        extra={
                            "confidence": final_confidence,
                            "dsl_is_null": final_dsl is None,
                            "conversation_id": out_conv_id,
                            "prior_turns_count": len(prior_turns),
                            "stream": True,
                            "usage": final_usage,
                            "output_chars": final_output_chars,
                        },
                    ))
                elif ev["type"] == "error":
                    # LLM call failed. Refund trial quota if applicable —
                    # the customer shouldn't be charged for the gateway's
                    # / Ark's hiccup.
                    if is_unactivated:
                        await ls.refund_unactivated_quota()
                    await _settle(conversation.TURN_FAILED, {"error": {
                        "code": ev.get("code") or "llm_generation_failed",
                        "message": str(ev.get("message") or "")[:300],
                    }})
                    settled = True
                    yield _sse(ev)
                else:
                    yield _sse(ev)
        except (GeneratorExit, asyncio.CancelledError):
            # 客户端断开（点了停止 / 关了页签）。这一问留着，标成中断，能重试。
            if not settled:
                await _settle(conversation.TURN_ABORTED)
                settled = True
            raise
        except Exception as e:  # noqa: BLE001
            if is_unactivated and not stream_ok:
                await ls.refund_unactivated_quota()
            await _settle(conversation.TURN_FAILED, {"error": {
                "code": "llm_generation_failed", "message": str(e)[:300],
            }})
            settled = True
            yield _sse({"type": "error", "message": str(e)})
        finally:
            # 流正常走完却没到 done / error（供应商半路断了）：也不能留 pending。
            if not settled:
                await _settle(conversation.TURN_ABORTED)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable nginx buffering if reverse-proxied
            "Connection": "keep-alive",
        },
    )


def _sse(payload: dict) -> bytes:
    """Format a payload dict as an SSE `data:` frame (UTF-8 bytes)."""
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")


# ─────────────────────────── /api/execute ───────────────────────────


# quota=False: this is a pure ES round-trip, no model call. Every page that
# renders a stat card fires it on load, so counting it drained the "200 AI
# calls/day" trial quota by ~5 per page view before the analyst asked anything.
@llm_post("/api/execute", quota=False, rpm_env="RST_RATELIMIT_EXECUTE", rpm=30.0)
async def execute(req: ExecuteRequest, request: Request):
    start = time.perf_counter()
    _check_index(req.index)
    user = current_user(request)
    try:
        validate_dsl(req.dsl)
    except Exception as e:
        raise ApiError("dsl_validation_failed", reason=e)

    # 界面的时间范围在这里才是保证：DSL 可能是用户手改过的、历史里回放的、或者
    # 下钻生成的，提示词管不到它们，这一层管得到。
    dsl, applied_window = await _apply_time_window(req.index, req.dsl, req.since, req.until)
    dsl = dsl if dsl is not None else req.dsl
    try:
        result = await execute_search(req.index, apply_default_sort(dsl))
    except Exception as e:
        raise es_api_error(e)
    duration_ms = int((time.perf_counter() - start) * 1000)
    hits = 0
    if isinstance(result, dict):
        total = (result.get("hits") or {}).get("total") or {}
        hits = total.get("value", 0) if isinstance(total, dict) else 0
    try:
        dsl_size = len(json.dumps(req.dsl, ensure_ascii=False))
    except Exception:
        dsl_size = -1
    logger.info(
        "execute",
        extra={
            "index": req.index,
            "dsl_size_bytes": dsl_size,
            "hits": hits,
            "duration_ms": duration_ms,
            "user": user,
        },
    )
    audit.fire_and_forget(audit.write_event(
        "execute",
        index=req.index,
        user=user,
        duration_ms=duration_ms,
        extra={"dsl_size_bytes": dsl_size, "hits": hits},
    ))
    # A query that returned data is the only evidence we get that the model
    # picked fields that exist on THIS cluster, so remember it as an example
    # for later questions. `question` is sent on an answer's first execution
    # only — a sort re-run or a drill-down is the same question with a
    # different DSL. Off the response path entirely: recording must never
    # slow down or fail a search. (fire_and_forget keeps a strong task ref.)
    # viewer 的成功查询不进库：这条库是共享的 few-shot 语料，只读账号不该有
    # 「影响别人（含管理员）生成结果」的写入权。读还是照读 —— 见 find_similar
    # 的 owner 过滤。
    if req.question and hits > 0 and effective_role(request) != "viewer":
        # 存的是套了窗口之后的 DSL：这份查询之所以有结果，时间窗是其中一个条件。
        # owner 必须是字符串：mapping 里是 keyword，塞 current_user() 那个 dict 会被
        # ES 拒成 document_parsing_exception，而这条走 fire_and_forget，异常被吞掉 ——
        # 开着登录的部署里 learned solutions 一条都没录进去过。用和 /api/generate
        # 同一个取主人的函数，两边算出来的 doc id 才对得上。
        audit.fire_and_forget(solutions.record_success(
            question=req.question, index=req.index, dsl=dsl, hits=hits,
            owner=_conv_owner(request),
        ))
    if applied_window is not None and isinstance(result, dict):
        # ES 的结果里不会有这个键，加在顶层不影响任何既有读取。
        return {**result, "time_window": applied_window.model_dump()}
    return result


# ─────────────────────────── 界面时间范围 ───────────────────────────


async def _apply_time_window(
    index: str, dsl: dict | None, since: str | None, until: str | None,
    mapping: dict | None = None, time_intent: dict | None = None,
) -> tuple[dict | None, AppliedTimeWindow | None]:
    """把界面选的时间范围套到 DSL 上，返回 (新 DSL, 告诉界面发生了什么)。

    优先级：**用户在问题里明确说的时间 > 界面上的筛选器**。

    这跟 Kibana 不一样，因为前提不一样：Kibana 的查询框里打不了日期，时间只有
    选择器一个入口；这里自然语言是一等入口，"23号登录失败最多的 10 个 IP" 里的
    "23号" 是用户刚刚打下的、最具体的意图，不该被一个早先设好的筛选器盖掉。

    问题赢的时候 DSL 一个字不改（模型写的时间条件就是答案），只把模型换算出的绝对
    区间回给界面 —— 界面据此把筛选器同步显示成那一段。同步是这条规则能成立的关键：
    否则筛选器写着「全部时间」、结果按 9 月 23 日跑，界面上两个地方互相矛盾。

    两个都空 = 全部时间 = 原样返回、不带 time_window，今天的行为一字不变。

    索引没有日期字段时不注入，但要回一个 `unsupported=True` —— 静默失效意味着
    用户以为筛了、其实没有，那比报错更糟。
    """
    if dsl is None:
        return dsl, None

    if time_intent and time_intent.get("since"):
        # 问题自己说了时间：DSL 不动，把它换算出的绝对区间告诉界面去同步筛选器。
        return dsl, AppliedTimeWindow(
            since=time_intent["since"], until=time_intent.get("until"),
            mode=time_window.MODE_QUESTION_WINS, question_text=time_intent.get("text"),
        )

    if not since and not until:
        return dsl, None
    try:
        mapping = mapping if mapping is not None else await get_mapping(index)
    except Exception:  # noqa: BLE001 — 读不到 mapping 不该让查询失败
        mapping = None
    field = time_window.resolve_time_field(mapping)
    if not field:
        return dsl, AppliedTimeWindow(since=since, until=until, unsupported=True)
    out, mode = time_window.apply_window(dsl, field, since, until)
    return out, AppliedTimeWindow(since=since, until=until, field=field, mode=mode)


# ─────────────────────────── /api/kibana-link ───────────────────────────


# 不调 LLM（不扣额度），但要限流：它是可以被刷的深链生成。
@llm_post("/api/kibana-link", quota=False,
          rpm_env="RST_RATELIMIT_KIBANA_LINK", rpm=120.0)
async def kibana_link(req: KibanaLinkRequest, request: Request):
    _check_index(req.index)
    user = current_user(request)
    # Origin/Referer let us derive a browser-reachable Kibana host when
    # KIBANA_PUBLIC_URL isn't set — otherwise the link inherits the internal
    # docker hostname and the user's browser can't resolve it.
    origin = trusted_origin(request)
    try:
        result = await build_kibana_link(req.index, req.dsl, request_origin=origin)
    except DataViewNotFound as e:
        raise ApiError("kibana_data_view_not_found", 404, reason=e)
    except Exception as e:
        raise ApiError("kibana_link_failed", 500, reason=e)
    audit.fire_and_forget(audit.write_event(
        "kibana_link", index=req.index, user=user,
    ))
    # 见 alerts_routes 同名字段：Origin 不被信任时深链落在内部主机名上，界面要说得出。
    return {**result, "origin_ignored": trusted_origin_ignored(request)}


# ─────────────────────────── /api/explain-log ───────────────────────────


@llm_post("/api/explain-log", rpm_env="RST_RATELIMIT_EXPLAIN_LOG", rpm=30.0)
async def explain_log_endpoint(req: ExplainLogRequest, request: Request):
    if not req.doc:
        raise ApiError("doc_empty")
    if req.index:
        _check_index(req.index)
    user = current_user(request)
    start = time.perf_counter()
    try:
        result = await explain_log(req.doc, req.index)
    except Exception as e:
        raise ApiError("explain_log_failed", 500, reason=e)
    duration_ms = int((time.perf_counter() - start) * 1000)
    try:
        doc_size = len(json.dumps(req.doc, ensure_ascii=False))
    except Exception:
        doc_size = -1
    license_status = ls.get_state()["status"]
    logger.info(
        "explain_log",
        extra={
            "index": req.index,
            "doc_size_bytes": doc_size,
            "log_type": result.get("log_type"),
            "severity": result.get("severity"),
            "confidence": result.get("confidence"),
            "duration_ms": duration_ms,
            "license_status": license_status,
            "user": user,
        },
    )
    audit.fire_and_forget(audit.write_event(
        "explain_log",
        index=req.index,
        user=user,
        license_status=license_status,
        duration_ms=duration_ms,
        extra={
            "log_type": result.get("log_type"),
            "severity": result.get("severity"),
            "confidence": result.get("confidence"),
        },
    ))
    return result


# ─────────────────────── /api/suggest-angles (再想几个角度) ───────────────────────


@llm_post("/api/suggest-angles", rpm_env="RST_RATELIMIT_SUGGEST_ANGLES", rpm=30.0)
async def suggest_angles_endpoint(req: SuggestAnglesRequest):
    """首页示例卡的「让 AI 再想几个角度」：把一句傻问题拆成几条具体问法，SSE 逐条出。

    帧：{type:"angle", text} × N，然后 {type:"done"}；模型出错是 {type:"error",
    message}（流已经开了，不能再换成 500）。只出问句不出 DSL，真正的查询仍走
    /api/generate。索引名由前端从 /api/indices 带过来（那条路由已经按白名单过滤
    过），这里只截长度。"""

    async def event_stream():
        yield b": connected\n\n"
        try:
            async for text in suggest_angles.suggest(
                req.question, req.indices, req.existing, req.lang,
            ):
                yield _sse({"type": "angle", "text": text})
            yield _sse({"type": "done"})
        except Exception as e:  # noqa: BLE001
            logger.warning("suggest_angles failed: %s", e)
            yield _sse({
                "type": "error",
                "message": ApiError("suggest_angles_failed", 500, reason=e).detail,
            })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ─────────────────────── /api/explain-result (结果解读) ───────────────────────


@llm_post("/api/explain-result", rpm_env="RST_RATELIMIT_EXPLAIN_RESULT", rpm=30.0)
async def explain_result_endpoint(req: ExplainResultRequest, request: Request):
    """Interpret a query's RESULT SET, not a single document.

    A `size:0` aggregation answer is a table of numbers with no next step — this
    turns it into 结论 / 可信度 / 下一步下钻. Same output shape as /api/explain-log
    so the frontend reuses one dialog."""
    if not req.dsl:
        raise ApiError("dsl_empty")
    if not req.aggregations and not req.sample_hits:
        raise ApiError("nothing_to_explain")
    if req.index:
        _check_index(req.index)
    user = current_user(request)
    start = time.perf_counter()
    try:
        result = await explain_result(
            question=req.question,
            dsl=req.dsl,
            aggregations=req.aggregations,
            sample_hits=req.sample_hits,
            total=req.total,
            index=req.index,
        )
    except Exception as e:
        raise ApiError("explain_result_failed", 500, reason=e)
    duration_ms = int((time.perf_counter() - start) * 1000)
    # Archive it like investigations and triage runs. Without this the analyst
    # pays for the interpretation again every time they want to re-read it, and
    # the reasoning behind a disposition is lost the moment the dialog closes.
    # Carry the question so the archive list says what was asked.
    audit.fire_and_forget(
        analysis_store.record(
            "result_explain", {**result, "question": req.question},
            owner=_conv_owner(request),
        )
    )
    license_status = ls.get_state()["status"]
    logger.info(
        "explain_result",
        extra={
            "index": req.index,
            "has_aggs": bool(req.aggregations),
            "sample_hits": len(req.sample_hits),
            "total": req.total,
            "severity": result.get("severity"),
            "confidence": result.get("confidence"),
            "duration_ms": duration_ms,
            "license_status": license_status,
            "user": user,
        },
    )
    audit.fire_and_forget(audit.write_event(
        "explain_result",
        index=req.index,
        user=user,
        license_status=license_status,
        duration_ms=duration_ms,
        extra={
            "severity": result.get("severity"),
            "confidence": result.get("confidence"),
        },
    ))
    return result


# ─────────────────────────── /api/investigate-alert ───────────────────────────


@llm_post("/api/investigate-alert", rpm_env="RST_RATELIMIT_INVESTIGATE", rpm=30.0)
async def investigate_alert_endpoint(req: InvestigateRequest, request: Request):
    if not req.alert:
        raise ApiError("alert_empty")
    _check_index(req.index)
    if not _feature_allowed("alert_investigation"):
        raise ApiError("feature_needs_standard", 403, feature="alert_investigation")
    user = current_user(request)
    start = time.perf_counter()
    agentic = agentic_investigate.agentic_enabled()
    try:
        if agentic:
            result = await agentic_investigate.agentic_investigate_alert(
                req.alert, req.index, window_minutes=req.window_minutes
            )
        else:
            result = await investigate_alert(req.alert, req.index, window_minutes=req.window_minutes)
    except Exception as e:
        raise ApiError("investigation_failed", 500, reason=e)
    _record_investigation(req, request, result, user, agentic, start)
    return result


def _record_investigation(
    req: "InvestigateRequest", request: Request, result: dict, user, agentic: bool, start: float
) -> None:
    """Log + audit + archive an investigation result. Shared by the blocking and
    the SSE endpoints so both paths record identically."""
    duration_ms = int((time.perf_counter() - start) * 1000)
    license_status = ls.get_state()["status"]
    logger.info(
        "investigate_alert",
        extra={
            "index": req.index,
            "agentic": agentic,
            "agentic_steps": result.get("agentic_steps"),
            "alert_type": result.get("alert_type"),
            "severity": result.get("severity"),
            "is_likely_fp": result.get("is_likely_false_positive"),
            "context_count": result.get("context_count"),
            "techniques": len(result.get("mitre_techniques") or []),
            "duration_ms": duration_ms,
            "license_status": license_status,
            "user": user,
        },
    )
    audit.fire_and_forget(audit.write_event(
        "investigate_alert",
        index=req.index,
        user=user,
        license_status=license_status,
        duration_ms=duration_ms,
        extra={
            "alert_type": result.get("alert_type"),
            "severity": result.get("severity"),
            "is_likely_fp": result.get("is_likely_false_positive"),
            "context_count": result.get("context_count"),
            "techniques": len(result.get("mitre_techniques") or []),
        },
    ))
    audit.fire_and_forget(
        analysis_store.record("investigation", result, owner=_conv_owner(request))
    )


# ─────────────────── /api/investigate-alert/stream (SSE) ───────────────────


# 桶与 /api/investigate-alert 共用 —— 改用流式不能绕开调查的限流。
@llm_post("/api/investigate-alert/stream")
async def investigate_alert_stream(req: InvestigateRequest, request: Request):
    """Streaming variant of /api/investigate-alert. Emits a `stage` SSE event
    between each pipeline step (fetch context → asset enrich → RAG → AI analysis),
    then one `result` event with the same payload the blocking endpoint returns.
    The blocking endpoint is unchanged for callers that don't want progress."""
    if not req.alert:
        raise ApiError("alert_empty")
    _check_index(req.index)
    if not _feature_allowed("alert_investigation"):
        raise ApiError("feature_needs_standard", 403, feature="alert_investigation")
    # SEC-CC-1: unlock the sealed core BEFORE the stream opens. Once the
    # generator is running, an exception inside it can't reach the
    # FeatureLocked handler — the client would see a broken stream, not a 403.
    feature_unlock.load_premium("alert_investigation")
    user = current_user(request)
    start = time.perf_counter()
    agentic = agentic_investigate.agentic_enabled()
    queue: asyncio.Queue = asyncio.Queue()

    async def _progress(evt: dict) -> None:
        await queue.put(evt)

    async def _run() -> None:
        try:
            if agentic:
                result = await agentic_investigate.agentic_investigate_alert(
                    req.alert, req.index, window_minutes=req.window_minutes, progress=_progress
                )
            else:
                result = await investigate_alert(
                    req.alert, req.index, window_minutes=req.window_minutes, progress=_progress
                )
        except Exception as e:  # noqa: BLE001
            await queue.put({"type": "error", "message": f"Investigation failed: {e}"})
            return
        _record_investigation(req, request, result, user, agentic, start)
        await queue.put({"type": "result", "result": result})

    async def event_stream():
        task = asyncio.create_task(_run())
        try:
            yield b": connected\n\n"
            while True:
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield b": ping\n\n"  # keep-alive through proxies
                    continue
                yield _sse(evt)
                if evt.get("type") in ("result", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ─────────────── /api/investigate-alert/notify (推送结论) ───────────────


@app.post("/api/investigate-alert/notify")
async def investigate_alert_notify(request: Request):
    """Push an investigation conclusion to configured Feishu targets — the exit
    that turns a confirmed finding into a team notification. Reuses the alert
    dispatch path (outbox → Feishu), so subject values are field-masked on egress
    exactly like real-time alerts. Returns how many targets it reached (0 = none
    configured, or none whose severity threshold this finding meets)."""
    if not _feature_allowed("alert_investigation"):
        raise ApiError("feature_needs_standard", 403, feature="alert_investigation")
    body = await request.json()
    inv = body.get("investigation") if isinstance(body, dict) else None
    if not isinstance(inv, dict) or not inv:
        raise ApiError("investigation_empty")

    # Normalize the investigation into the alert shape render_alert_card expects.
    assets = inv.get("affected_assets") or []
    subj_field = subj_value = None
    if assets and isinstance(assets[0], dict):
        subj_field = assets[0].get("type")
        subj_value = assets[0].get("id")
    actions = inv.get("recommended_actions") or []
    alert = {
        "severity": inv.get("severity", "info"),
        "rule_name": inv.get("alert_type") or "调查结论",
        "attack_intent": inv.get("alert_type"),
        "subject_field": subj_field,
        "subject_value": subj_value,
        "recommendation": actions[0] if actions else inv.get("summary"),
    }
    from .notify import outbox
    ref = f"investigate:{int(time.time() * 1000)}"
    try:
        n = await outbox.dispatch_alert(alert, ref)
    except Exception as e:
        raise ApiError("push_failed", 500, reason=e)
    return {"dispatched": n}


# ─────────────── /api/triage/escalate (升级 → 值班推送) ───────────────


@app.post("/api/triage/escalate")
async def triage_escalate(request: Request):
    """Notify configured Feishu targets that a triage cluster was escalated (升级) —
    turns the 'escalated' disposition from a dead label into an on-call push. Reuses
    the alert dispatch path (outbox → Feishu), so subject values are field-masked on
    egress just like real-time alerts. Returns how many targets it reached (0 = none
    configured, or none whose severity threshold this cluster meets)."""
    if not _feature_allowed("alert_triage"):
        raise ApiError("feature_needs_standard", 403, feature="alert_triage")
    body = await request.json()
    cluster = body.get("cluster") if isinstance(body, dict) else None
    if not isinstance(cluster, dict) or not cluster:
        raise ApiError("cluster_empty")

    intent = cluster.get("attack_intent") or cluster.get("rule_id") or "告警聚类"
    rank = cluster.get("priority_rank")
    rule_name = f"[升级 #{rank}] {intent}" if rank is not None else f"[升级] {intent}"
    count = cluster.get("count")
    alert = {
        "severity": cluster.get("severity", "info"),
        "rule_name": rule_name,
        "attack_intent": cluster.get("attack_intent"),
        "subject_field": cluster.get("subject_field"),
        "subject_value": cluster.get("subject_value"),
        "recommendation": cluster.get("recommendation")
        or (f"{count} 条告警，已由分析员升级，请值班跟进。" if count else "已由分析员升级，请值班跟进。"),
    }
    from .notify import outbox
    # Timestamped ref so re-escalating the same cluster isn't deduped away.
    ref = f"escalate:{cluster.get('cluster_id') or 'x'}:{int(time.time() * 1000)}"
    try:
        n = await outbox.dispatch_alert(alert, ref)
    except Exception as e:
        raise ApiError("push_failed", 500, reason=e)
    return {"dispatched": n}


# ─────────────── /api/report/to-feishu (报告转发飞书) ───────────────


@app.post("/api/report/to-feishu")
async def report_to_feishu(request: Request):
    """Forward an investigation REPORT to Feishu — as a shareable cloud Docs page
    (full report, no truncation) and/or a group card (summary + doc link). The
    doc path uses a Feishu custom app (Open API); the group path reuses the bot
    webhook delivery. Either half degrades to an error string if unconfigured."""
    if not _feature_allowed("alert_investigation"):
        raise ApiError("feature_needs_standard", 403, feature="alert_investigation")
    body = await request.json()
    if not isinstance(body, dict):
        raise ApiError("body_not_object")
    title = str(body.get("title") or "安全调查报告")
    markdown = str(body.get("markdown") or "")
    if not markdown.strip():
        raise ApiError("markdown_empty")
    # Feishu is a third-party SaaS, so this is an egress boundary — the same one
    # outbox.dispatch_alert masks at. This route was skipping it: an
    # investigation report is assembled from raw hits and routinely carries
    # source IPs, account emails and whatever tokens showed up in a log line,
    # and all of it went out verbatim into a cloud document.
    from .field_masking import mask_text
    title = mask_text(title)
    markdown = mask_text(markdown)
    to_doc = bool(body.get("to_doc", True))
    to_group = bool(body.get("to_group", True))
    severity = str(body.get("severity") or "high")

    from .notify import config, feishu, feishu_docs, outbox
    result: dict[str, Any] = {"doc_url": None, "dispatched": 0, "errors": []}

    doc_url = None
    if to_doc:
        try:
            doc_url = await feishu_docs.create_report_doc(title, markdown)
            result["doc_url"] = doc_url
        except Exception as e:  # noqa: BLE001
            result["errors"].append(f"云文档：{e}")

    if to_group:
        targets = await config.targets_for_alert(severity)
        if not targets:
            result["errors"].append("群消息：未配置飞书 webhook 目标（在 运营 → 通知 配置）")
        else:
            card = feishu.render_report_link_card(
                title, severity, doc_url,
                base_url=(os.environ.get("RST_PUBLIC_BASE_URL") or "").strip(),
            )
            ref = f"invreport:{int(time.time() * 1000)}"
            for t in targets:
                try:
                    if await outbox.enqueue("report", ref, t, card):
                        result["dispatched"] += 1
                except Exception as e:  # noqa: BLE001
                    result["errors"].append(f"群消息（{t.get('name', '?')}）：{e}")
    return result


# ─────────────────────────── /api/field-dict ───────────────────────────


@app.post("/api/field-dict")
async def field_dict_endpoint(req: FieldDictRequest, request: Request):
    if not req.index:
        raise ApiError("index_required")
    _check_index(req.index)
    user = current_user(request)
    start = time.perf_counter()
    try:
        result = await get_field_dictionary(req.index)
    except Exception as e:
        raise ApiError("field_dict_failed", reason=e)
    duration_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "field_dict",
        extra={
            "index": req.index,
            "doc_count": result.get("doc_count"),
            "fields_count": len(result.get("fields") or []),
            "truncated": result.get("truncated"),
            "duration_ms": duration_ms,
            "user": user,
        },
    )
    audit.fire_and_forget(audit.write_event(
        "field_dict",
        index=req.index,
        user=user,
        duration_ms=duration_ms,
        extra={
            "doc_count": result.get("doc_count"),
            "fields_count": len(result.get("fields") or []),
        },
    ))
    return result


# ─────────────────────────── /api/detection-rule/generate (v1.0.4) ───────────────────────────


@llm_post("/api/detection-rule/generate",
          rpm_env="RST_RATELIMIT_DETECTION_RULE", rpm=30.0)
async def detection_rule_generate(req: DetectionRuleRequest, request: Request):
    if not req.question or not req.question.strip():
        raise ApiError("question_empty")
    _check_index(req.index)
    if not _feature_allowed("detection_rule_copilot"):
        raise ApiError("feature_needs_standard", 403, feature="detection_rule_copilot")
    user = current_user(request)
    start = time.perf_counter()
    try:
        mapping = await get_mapping(req.index)
    except Exception as e:
        raise es_api_error(e)
    try:
        result = await generate_detection_rule(
            req.question, req.index, mapping, req.rule_type_hint,
        )
    except FeatureLocked as e:
        # SEC-CC-1: the sealed engine could not be unlocked on this host — the
        # license isn't entitled / is bound elsewhere / the keyring is absent.
        # Fail SAFE (feature off), the rest of the product keeps running.
        logger.warning("detection_rule_feature_locked", extra={"error": str(e)})
        raise ApiError("feature_sealed", 403, feature="detection_rule_copilot")
    except ValueError as e:
        raise ApiError("detection_rule_rejected", 422, reason=e)
    except Exception as e:
        raise ApiError("detection_rule_failed", 500, reason=e)
    duration_ms = int((time.perf_counter() - start) * 1000)
    license_status = ls.get_state()["status"]
    logger.info(
        "detection_rule_generate",
        extra={
            "index": req.index,
            "rule_type": result.get("rule_type"),
            "confidence": result.get("confidence"),
            "refused": result.get("rule") is None,
            "duration_ms": duration_ms,
            "license_status": license_status,
            "user": user,
        },
    )
    audit.fire_and_forget(audit.write_event(
        "detection_rule_generate",
        index=req.index,
        user=user,
        license_status=license_status,
        duration_ms=duration_ms,
        extra={
            "rule_type": result.get("rule_type"),
            "confidence": result.get("confidence"),
            "refused": result.get("rule") is None,
        },
    ))
    return result


# ─────────────────────────── /api/triage/batch (v1.0.5) ───────────────────────────


# 扇出型（一次请求打很多次 LLM），默认限得更死。
@llm_post("/api/triage/batch", rpm_env="RST_RATELIMIT_TRIAGE_BATCH", rpm=6.0)
async def triage_batch_endpoint(req: TriageBatchRequest, request: Request):
    if req.alerts is None and not req.index:
        raise ApiError("alerts_or_index_required")
    if req.index:
        _check_index(req.index)
    if not _feature_allowed("alert_triage"):
        raise ApiError("feature_needs_standard", 403, feature="alert_triage")
    user = current_user(request)
    start = time.perf_counter()
    try:
        result = await triage_alerts(
            req.alerts,
            index=req.index,
            query=req.query,
            window_minutes=req.window_minutes,
            max_alerts=req.max_alerts,
            max_clusters_to_llm=req.max_clusters_to_llm,
        )
    except (HTTPException, FeatureLocked):
        # FeatureLocked has its own app-level handler (403 + feature_sealed);
        # swallowing it here turned "not licensed" into a 500 with the raw
        # English exception text on the triage page.
        raise
    except Exception as e:
        msg = str(e)
        if "timed out" in msg.lower() or "timeout" in msg.lower():
            raise ApiError("llm_timeout", 504, reason=msg)
        raise ApiError("triage_failed", 500, reason=e)
    duration_ms = int((time.perf_counter() - start) * 1000)
    license_status = ls.get_state()["status"]
    logger.info(
        "triage_batch",
        extra={
            "index": req.index,
            "total_alerts": result.get("total_alerts"),
            "total_clusters": result.get("total_clusters"),
            "scored_clusters": result.get("scored_clusters"),
            "truncated": result.get("truncated"),
            "degraded": result.get("degraded"),
            "duration_ms": duration_ms,
            "license_status": license_status,
            "user": user,
        },
    )
    audit.fire_and_forget(audit.write_event(
        "triage_batch",
        index=req.index,
        user=user,
        license_status=license_status,
        duration_ms=duration_ms,
        extra={
            "total_alerts": result.get("total_alerts"),
            "total_clusters": result.get("total_clusters"),
            "scored_clusters": result.get("scored_clusters"),
            "truncated": result.get("truncated"),
        },
    ))
    audit.fire_and_forget(
        analysis_store.record("triage", result, owner=_conv_owner(request))
    )
    return result


# ─────────────────────────── /api/report/incident (v1.0.3) ───────────────────────────


@llm_post("/api/report/incident", rpm_env="RST_RATELIMIT_REPORT_INCIDENT", rpm=6.0)
async def incident_report_endpoint(req: IncidentReportRequest, request: Request):
    if req.alert is None and not req.alert_id and req.investigation is None:
        raise ApiError("incident_input_required")
    _check_index(req.index)
    if not _feature_allowed("alert_investigation"):
        raise ApiError("incident_report_needs_standard", 403)
    user = current_user(request)
    start = time.perf_counter()
    try:
        result = await generate_incident_report(
            index=req.index,
            alert=req.alert,
            alert_id=req.alert_id,
            investigation=req.investigation,
            window_minutes=req.window_minutes,
            include_evidence=req.include_evidence,
            evidence_limit=req.evidence_limit,
        )
    except ApiError:
        raise
    except ValueError as e:
        raise ApiError("invalid_request", reason=e)
    except Exception as e:
        raise ApiError("incident_report_failed", 500, reason=e)
    duration_ms = int((time.perf_counter() - start) * 1000)
    license_status = ls.get_state()["status"]
    inv = result.get("investigation") or {}
    logger.info(
        "incident_report",
        extra={
            "index": req.index,
            "alert_id": req.alert_id,
            "alert_type": inv.get("alert_type"),
            "severity": inv.get("severity"),
            "evidence_count": result.get("evidence_count"),
            "markdown_chars": len(result.get("markdown") or ""),
            "duration_ms": duration_ms,
            "license_status": license_status,
            "user": user,
        },
    )
    audit.fire_and_forget(audit.write_event(
        "incident_report",
        index=req.index,
        user=user,
        license_status=license_status,
        duration_ms=duration_ms,
        extra={
            "alert_id": req.alert_id,
            "alert_type": inv.get("alert_type"),
            "severity": inv.get("severity"),
            "evidence_count": result.get("evidence_count"),
            "markdown_chars": len(result.get("markdown") or ""),
        },
    ))
    return result


# ─────────────────────────── Conversations ───────────────────────────


def _conv_owner(request: Request) -> str:
    """Owner bucket for a conversation: the SSO user, or a shared default in
    demo/single-user mode (no SSO). Conversations are personal state."""
    return user_state.owner_for("history", current_user(request))


@app.get("/api/conversations/{conv_id}")
async def get_conversation_endpoint(conv_id: str, request: Request):
    entry = await conversation.get(conv_id, owner=_conv_owner(request))
    if not entry:
        raise ApiError("conversation_not_found", 404)
    return entry


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation_endpoint(conv_id: str, request: Request):
    deleted = await conversation.delete(conv_id, owner=_conv_owner(request))
    if not deleted:
        # Missing or owned by someone else — 404 (matches GET) instead of a
        # 200 {ok:false} that a client has to special-case.
        raise ApiError("conversation_not_found", 404)
    return {"ok": True}


# ─────────────────────────── Analysis archive ───────────────────────────


@app.get("/api/analysis")
async def analysis_list_endpoint(
    request: Request,
    kind: str | None = None,
    limit: int = 30,
    before: float | None = None,
    q: str | None = None,
    since: float | None = None,
):
    limit = max(1, min(limit, 100))
    return await analysis_store.list_records(
        kind, limit, before, owner=_conv_owner(request), q=q, since=since
    )


@app.get("/api/analysis/{rec_id}")
async def analysis_detail_endpoint(rec_id: str, request: Request):
    rec = await analysis_store.get_record(rec_id, owner=_conv_owner(request))
    if not rec:
        raise ApiError("analysis_record_not_found", 404)
    return rec


# ─────────────────────────── /api/feedback ───────────────────────────


@app.post("/api/feedback")
async def feedback(req: FeedbackRequest, request: Request):
    if not req.correct:
        # A thumbs-down retires the worked example this answer would otherwise
        # have become — identified by the question, not by the DSL: what the UI
        # sends here is the GENERATED dsl, while the solutions store holds the
        # EXECUTED one (size / sort / track_total_hits injected client-side).
        # owner 同样必须是字符串（见 /api/execute 那处）：这里传 dict 的话，
        # 差评退役的是一条 id 对不上的记录，等于什么都没退役。
        audit.fire_and_forget(solutions.reject_by_question(
            req.question, req.index, _conv_owner(request), "thumbs_down",
        ))
        # The comment box next to the thumbs-down is where a correction gets
        # typed in full ("event_type=7 才是转账失败"). It used to dead-end in
        # failed_cases.yaml, which only we ever read.
        if req.comment and req.comment.strip() and is_admin(request):
            audit.fire_and_forget(corrections.capture(
                correction=req.comment,
                owner=_conv_owner(request),
                question=req.question,
                index=req.index,
                dsl=req.dsl,
                # Skip the lexical gate: the analyst pressed 👎 and was asked
                # what was wrong, so "转账失败对应 event_type=7" with no "不对"
                # in it is still a correction. Whether it is worth keeping is
                # the distiller's call, not the gate's.
                gated=False,
            ))
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": req.question,
        "index": req.index,
        "dsl": req.dsl,
        "correct": req.correct,
        "comment": req.comment,
        "suggested_dsl": req.suggested_dsl,
        "prompt_version": req.prompt_version,
        "dsl_was_edited": req.dsl_was_edited,
    }
    if req.correct and not req.comment and req.suggested_dsl is None:
        logger.info(
            "feedback_positive",
            extra={"index": req.index, "prompt_version": req.prompt_version},
        )
        return {"status": "logged"}

    async with _FAILED_CASES_LOCK:
        try:
            data = _load_failed_cases()
            cases = data.setdefault("cases", [])
            cases.append(record)
            # Bound the file: an unauthenticated feedback loop must not grow it
            # without limit (each write rewrites the whole file → O(n) per POST).
            if len(cases) > _FAILED_CASES_MAX:
                del cases[: len(cases) - _FAILED_CASES_MAX]
            _atomic_write_yaml(data)
        except Exception as e:
            raise ApiError("feedback_persist_failed", 500, reason=e)

    logger.info(
        "feedback_correction" if req.correct else "feedback_negative",
        extra={
            "index": req.index,
            "prompt_version": req.prompt_version,
            "has_comment": bool(req.comment),
            "has_suggested": req.suggested_dsl is not None,
            "dsl_was_edited": bool(req.dsl_was_edited),
        },
    )
    return {"status": "saved"}


_FAILED_CASES_MAX = 5000  # keep the most-recent N; older corrections age out


def _load_failed_cases() -> dict:
    if not _FAILED_CASES_PATH.exists():
        return {"cases": []}
    try:
        with open(_FAILED_CASES_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        # Do NOT swallow a parse error into an empty dict: the very next append
        # would _atomic_write_yaml an empty file over the real data, silently
        # destroying every prior correction. Surface it instead so the caller
        # 500s and the operator fixes/removes the file — data stays intact.
        raise RuntimeError(
            f"failed_cases store at {_FAILED_CASES_PATH} is unreadable/corrupt: {e}"
        )
    if not isinstance(data, dict):
        data = {}
    if "cases" not in data or not isinstance(data["cases"], list):
        data["cases"] = []
    return data


def _atomic_write_yaml(data: dict) -> None:
    _FAILED_CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _FAILED_CASES_PATH.with_suffix(_FAILED_CASES_PATH.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp_path, _FAILED_CASES_PATH)


# ─────────────────────────── Health ───────────────────────────


@app.get("/healthz")
@app.get("/api/health")
async def healthz():
    """Liveness probe — most LB / ingress controllers default to /api/health
    or /health, so we accept both paths for the same payload."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    # `es_configured` separates "never set up" from "set up but currently down",
    # which the UI treats very differently: the first gets the setup dialog, the
    # second a banner. Reported on both branches — a fresh install is exactly the
    # case where this endpoint answers 503 and the answer still has to be usable.
    configured = {"es_configured": bool(os.environ.get("ES_URL", "").strip())}
    # Ping first so a down ES returns fast; only when ES is reachable do we
    # re-probe the es_write snapshot (self-heals it once write perms / ES recover,
    # without adding a write attempt that would hang while ES is down).
    try:
        ok = await ping()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "es": str(e), **configured, **preflight.results()},
        )
    if not ok:
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "es": "ping returned False", **configured, **preflight.results()},
        )
    try:
        await preflight.recheck_es_write()
    except Exception:  # noqa: BLE001
        pass
    return {"status": "ready", "es": "ok", **configured, **preflight.results()}


# ─────────────────────────── License ───────────────────────────


@app.get("/api/license/status")
async def license_status():
    return ls.get_state()


@app.get("/api/license/server-guid")
async def license_server_guid(request: Request):
    # DEPRECATED (2026-07-07): server_guid is no longer a user-facing binding
    # ID. Both online and offline activation bind to host_fingerprint; server_guid
    # is retained only as a fingerprint salt + heartbeat audit metadata. The
    # LicensePage UI no longer calls this — kept admin-gated for internal/debug.
    require_admin(request)
    return {"server_guid": get_server_guid()}


@app.get("/api/license/host-fingerprint")
async def license_host_fingerprint(request: Request):
    # SEC-FP-1 hardware fingerprint (64-hex) — what `issue-offline --fingerprint`
    # binds an air-gapped license to. Surfaced so ops can read it from the UI
    # instead of running a one-liner in the container. Admin-gated like the GUID.
    require_admin(request)
    try:
        return {"host_fingerprint": get_host_fingerprint()}
    except Exception as e:  # noqa: BLE001
        # Any hardware-identity failure (RSTLicHardwareUnavailable, or an import/
        # platform error) is an operator-config issue, not a server fault — 503
        # with an actionable message rather than an opaque 500.
        raise ApiError("machine_id_unreadable", 503, reason=e)


@app.post("/api/license/activate")
async def license_activate(req: ActivateRequest):
    try:
        return await ls.activate_from_text(req.license_key)
    except InvalidLicense as e:
        raise ApiError("license_activate_failed", reason=e)
    except Exception as e:
        raise ApiError("license_activate_error", 500, reason=e)


@app.post("/api/license/reload")
async def license_reload(request: Request):
    # 旁边的 server-guid / host-fingerprint 都要管理员，这两条漏了：analyst 打一次
    # deactivate 就能把整个部署打回未激活，全员降到试用额度。
    require_admin(request)
    await ls.reload_license()
    return ls.get_state()


@app.post("/api/license/deactivate")
async def license_deactivate(request: Request):
    """Clear the local activation record on this host → revert to unactivated.

    Operator action (same protection level as /activate — the gateway auth
    middleware / reverse-proxy fronts it). Lets an operator swap or remove the
    installed license without editing files on disk.
    """
    require_admin(request)
    try:
        return await ls.deactivate()
    except Exception as e:
        raise ApiError("license_deactivate_error", 500, reason=e)


# ─────────────────────────── /api/me (SSO identity) ───────────────────────────


@app.get("/api/me")
async def whoami(request: Request):
    """Current end-user identity + whether this user has admin privilege.
    The SPA uses `is_admin` to show/hide admin UI (Provider / Settings save)
    without having to wait for a 403 round-trip."""
    # `current_user()` now answers under password login too, so the display-only
    # identity that used to be assembled here is gone: there is one identity,
    # and it is the same one that picks the state bucket and lands in audit.
    # The migration worry that kept them apart — an existing deployment's
    # history appearing to vanish the day it turns on login — is handled where
    # it belongs, by the shared-bucket fallback in user_state.
    u = current_user(request)
    return {
        "authenticated": u is not None,
        "user": u,
        "sso_enabled": sso_enabled(),
        # The SPA reads these two to decide whether to render the login page at
        # all. With login off it must not: a login form no backend accepts is
        # worse than none, it implies a protection that is not there.
        "login_enabled": session_auth.login_enabled(),
        "is_admin": is_admin(request),
        # The live role, so the SPA can hide what this user cannot do. Hiding
        # is a courtesy, not the control: every one of those actions is refused
        # again by the backend. None means the deployment has no role opinion
        # about this caller (ops token, or a proxy-header identity with no
        # account) — the SPA treats that as "show everything and let the
        # backend answer", which is what it did before roles existed.
        "role": effective_role(request),
        "multi_user": user_db.enabled(),
        "logout_url": os.environ.get("RST_SSO_LOGOUT_URL", "/oauth2/sign_out"),
    }


# ───────────────────────── password login (single operator) ─────────────────


@app.post("/api/auth/login")
async def auth_login(req: LoginRequest, request: Request):
    """Exchange the operator password for a session cookie.

    404 when password login is not configured, so a deployment running SSO or
    Basic Auth does not advertise a second way in.
    """
    if not session_auth.login_enabled():
        raise ApiError("password_login_disabled", 404)

    ip = client_ip_from_request(request) or "unknown"

    # Refuse a remote login while the shipped password is still in place. The
    # check is before the throttle and before credential verification: it is a
    # statement about the deployment, not about this attempt, so it must not
    # depend on the caller getting the password right.
    if session_auth.default_password_blocks(ip):
        logger.warning("login_refused_default_password", extra={"client_ip": ip})
        raise ApiError("default_password_refused", 403)

    if session_auth.throttled(ip, req.username):
        raise ApiError("login_throttled", 429)

    if not session_auth.verify_credentials(req.username, req.password):
        session_auth.record_failure(ip, req.username)
        logger.warning("login_failed", extra={"client_ip": ip})
        # One message for both halves — telling the caller the account name
        # was right would hand them half the credential.
        raise ApiError("bad_credentials", 401)

    session_auth.clear_failures(ip, req.username)
    logger.info("login_ok", extra={"client_ip": ip})
    resp = JSONResponse({"ok": True})
    # Issue for the stored account name rather than whatever casing/padding the
    # form sent, so the identity that reaches audit and the state buckets is one
    # value and not one per typo.
    account = user_db.get(req.username) or {}
    session_auth.set_session_cookie(
        resp, request, str(account.get("username") or session_auth.username())
    )
    return resp


@app.post("/api/auth/password")
async def auth_change_password(req: PasswordChangeRequest, request: Request):
    """Change your own password. Not an admin operation — everyone has one.

    Exempt from the read-only gate on purpose: a viewer must be able to rotate
    their own credential. Requires the current password, so a borrowed session
    cannot be used to lock the real owner out.

    Every other session this account holds is dropped, because changing a
    password is what you do when you think someone else has it. The one making
    the change gets a fresh cookie so it does not sign itself out.
    """
    user = current_user(request)
    name = str((user or {}).get("username") or "")
    if not name or (user or {}).get("source") != "password":
        raise ApiError("password_change_not_supported", 403)
    if not session_auth.verify_credentials(name, req.current_password):
        raise ApiError("current_password_wrong", 401)
    if len(req.new_password) < 8:
        raise ApiError("password_too_short")

    new_hash = session_auth.hash_password(req.new_password)
    if user_db.enabled():
        try:
            user_db.update_user(name, password_hash=new_hash)
        except ApiError:
            raise
        except ValueError as e:
            raise ApiError("invalid_request", reason=e)
    else:
        # Single-account deployment: the hash lives in the environment and only
        # the operator can change it. Say so instead of pretending to succeed.
        raise ApiError("password_in_env_only")
    session_store.revoke_all(name)
    resp = JSONResponse({"ok": True})
    session_auth.set_session_cookie(resp, request, name)
    return resp


# ─────────────────────────── user management ───────────────────────────
#
# Admin-only, and additionally useless without RST_USER_DB_URL — `user_db`
# refuses every write with a message saying so, which is a better answer than
# hiding the endpoints and leaving the operator to guess.


def _users_payload() -> dict:
    return {"users": user_db.list_users(), "roles": list(user_db.ROLES),
            "multi_user": user_db.enabled()}


async def _users_payload_off_loop() -> dict:
    """用户表的读写都是同步 psycopg，而这几条都是 async 路由 —— 直接调会把
    整个事件循环卡在一次数据库往返上，不只是这一个请求。写完紧接着读更是
    必中：每个写都 `invalidate()`，所以后面那次 `list_users()` 一定是冷读。"""
    return await asyncio.to_thread(_users_payload)


@app.get("/api/users")
async def users_list(request: Request):
    require_admin(request)
    return await _users_payload_off_loop()


@app.post("/api/users")
async def users_create(req: UserCreateRequest, request: Request):
    require_admin(request)
    if len(req.password) < 8:
        raise ApiError("password_min_length")
    try:
        await asyncio.to_thread(
            user_db.create_user, req.username, session_auth.hash_password(req.password), req.role
        )
    except ApiError:
        raise
    except ValueError as e:
        raise ApiError("invalid_request", reason=e)
    logger.info("user_created", extra={"username": req.username, "role": req.role})
    return await _users_payload_off_loop()


@app.patch("/api/users/{username}")
async def users_update(username: str, req: UserUpdateRequest, request: Request):
    """Change a role, suspend an account, or reset a password.

    Suspending drops that account's live sessions, and so does resetting its
    password. A role change deliberately does not: authorisation reads the live
    role on every request, so a demotion is already in force on the demoted
    user's next click. Signing them out as well would only make the change look
    like it needed a re-login, which is the behaviour this phase set out to
    avoid.
    """
    require_admin(request)
    me = str((current_user(request) or {}).get("username") or "")
    if req.disabled and username.strip() == me:
        raise ApiError("cannot_disable_self")
    if req.password is not None and len(req.password) < 8:
        raise ApiError("password_min_length")
    try:
        await asyncio.to_thread(
            user_db.update_user,
            username,
            password_hash=(
                session_auth.hash_password(req.password) if req.password is not None else None
            ),
            role=req.role,
            disabled=req.disabled,
        )
    except ApiError:
        raise
    except ValueError as e:
        raise ApiError("invalid_request", reason=e)
    if req.disabled or req.password is not None:
        session_store.revoke_all(username.strip())
    logger.info("user_updated", extra={"username": username})
    return await _users_payload_off_loop()


@app.delete("/api/users/{username}")
async def users_delete(username: str, request: Request):
    require_admin(request)
    me = str((current_user(request) or {}).get("username") or "")
    if username.strip() == me:
        raise ApiError("cannot_delete_self")
    try:
        await asyncio.to_thread(user_db.delete_user, username)
    except ApiError:
        raise
    except ValueError as e:
        raise ApiError("invalid_request", reason=e)
    session_store.revoke_all(username.strip())
    logger.info("user_deleted", extra={"username": username})
    return await _users_payload_off_loop()


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    # Withdraw the session server-side, not just the cookie. Deleting the cookie
    # asks the browser to forget a credential that kept working for the rest of
    # its TTL — which made "sign out" untrue on any device that had copied it.
    session_auth.revoke_session(request)
    resp = JSONResponse({"ok": True})
    session_auth.clear_session_cookie(resp)
    return resp


# ─────────────────────────── LLM Providers (v1.0) ───────────────────────────


@app.get("/api/llm/providers")
async def llm_providers_status():
    """Returns the configured LLM providers + per-provider health stats."""
    return llm_router.get_router().status()


@app.post("/api/llm/reload")
async def llm_providers_reload(request: Request):
    """Re-read llm_providers.yml from disk. Useful after editing config in place."""
    require_admin(request)
    llm_router.reset()
    embeddings.reset()
    return llm_router.get_router().status()


@app.post("/api/llm/providers/save")
async def llm_providers_save(req: LLMProvidersSaveRequest, request: Request):
    """Write llm_providers.yml from UI input and reload the router.

    Empty api_key means "keep existing"; pass a non-empty value to rotate.
    Requires admin auth (RST_ADMIN_TOKEN or localhost in dev mode).
    """
    require_admin(request)
    if not req.providers:
        raise ApiError("providers_empty")
    try:
        result = llm_router.save_providers(req.providers)
        embeddings.reset()
        return result
    except ApiError:
        raise
    except ValueError as e:
        raise ApiError("invalid_request", reason=e)
    except Exception as e:  # noqa: BLE001
        raise ApiError("save_failed", 500, reason=e)


# ─────────────────────────── Embedding config (GUI) ───────────────────────────


def _embedding_status(cfg: dict | None) -> str:
    """enabled / disabled / misconfigured for the settings status bar."""
    if cfg is not None:
        if not cfg["enabled"]:
            return "disabled"
        if not cfg["model"] or cfg["dims"] <= 0:
            return "misconfigured"
        return "enabled"
    # No yml config — env fallback still counts as enabled.
    return "enabled" if embeddings.embedding_configured() else "disabled"


async def _kb_index_dims() -> int | None:
    try:
        return await rag.get_kb().index_dims()
    except Exception:  # noqa: BLE001
        return None


@app.get("/api/embedding/config")
async def embedding_config():
    """Read the embedding config + KB status. api_key is masked (last4 only)."""
    cfg = embeddings.load_embedding_config()
    key = (cfg or {}).get("api_key") or ""
    return {
        "model": (cfg or {}).get("model", ""),
        "base_url": (cfg or {}).get("base_url", ""),
        "api_key_set": bool(key),
        "api_key_last4": key[-4:] if key else "",
        "dims": (cfg or {}).get("dims", 0),
        "enabled": (cfg or {}).get("enabled", False),
        "status": _embedding_status(cfg),
        "kb_index_dims": await _kb_index_dims(),
    }


def _effective_form(body) -> tuple[str, str, str]:
    """Resolve (model, base_url, api_key) with blank api_key/base_url inheriting
    the currently-stored embedding config (mirror ProvidersCard "blank = keep")."""
    stored = embeddings.load_embedding_config() or {}
    model = (body.model or "").strip()
    base_url = (body.base_url or "").strip() or stored.get("base_url", "")
    api_key = (body.api_key or "").strip() or stored.get("api_key", "")
    return model, base_url, api_key


@app.post("/api/embedding/test")
async def embedding_test(req: EmbeddingTestRequest, request: Request):
    """Probe the (unsaved) form values. Never writes. Returns {ok, dims|error}."""
    require_admin(request)
    model, base_url, api_key = _effective_form(req)
    if not model:
        return {"ok": False, "error": "model 必填"}
    try:
        dims = await embeddings.probe_embedding(model, base_url, api_key)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:300]}
    return {"ok": True, "dims": dims}


@app.post("/api/embedding/save")
async def embedding_save(req: EmbeddingSaveRequest, request: Request):
    """Dimension guard → write yml → reset embedding singleton."""
    require_admin(request)
    model, base_url, api_key = _effective_form(req)
    # 1. model required
    if not model:
        raise ApiError("model_required")
    # 2. probe → real dims (never writes on failure)
    try:
        real_dims = await embeddings.probe_embedding(model, base_url, api_key)
    except Exception as e:  # noqa: BLE001
        raise ApiError("connection_test_failed", reason=str(e)[:300])
    # 3. dims guard: body value is advisory — real probe wins (warning, no error)
    if req.dims and req.dims != real_dims:
        logger.warning(
            "embedding_dims_autocorrected",
            extra={"submitted": req.dims, "real": real_dims},
        )
    # 4. KB index guard: existing index at a different width → 409, no write
    index_dims = await _kb_index_dims()
    if index_dims is not None and index_dims != real_dims:
        raise ApiError("kb_dim_mismatch", 409, index_dims=index_dims, real_dims=real_dims)
    # 5. write + reset singleton
    embeddings.save_embedding_config({
        "model": model,
        "base_url": (req.base_url or "").strip(),   # persist the raw form base_url ("" = reuse chat)
        "api_key": api_key,
        "dims": real_dims,
        "enabled": bool(req.enabled),
    })
    embeddings.reset()
    return {"ok": True, "dims": real_dims, "status": "enabled" if req.enabled else "disabled"}


# ─────────────────────────── /api/audit/events (Round 6) ───────────────────────────


@app.get("/api/audit/events")
async def audit_events(
    request: Request,
    from_ts: str | None = None,
    to_ts: str | None = None,
    action: str | None = None,
    user: str | None = None,
    target_index: str | None = None,
    outcome: str | None = None,
    size: int = 50,
    offset: int = 0,
):
    """Read the gateway audit index. Each filter is optional."""
    require_admin(request)
    if size <= 0 or size > 500:
        raise ApiError("size_out_of_range")
    if offset < 0:
        raise ApiError("offset_negative")
    from .es_client import get_es

    filters: list[dict] = []
    rng: dict = {}
    if from_ts:
        rng["gte"] = from_ts
    if to_ts:
        rng["lte"] = to_ts
    if rng:
        filters.append({"range": {"@timestamp": rng}})
    else:
        # Default to last 24h so the page never queries the entire history
        filters.append({"range": {"@timestamp": {"gte": "now-24h"}}})

    # The audit index has no explicit mapping — string fields are dynamic text,
    # so exact filters must target the `.keyword` subfield (same as reports.py).
    if action:
        filters.append({"term": {"action.keyword": action}})
    if user:
        filters.append({"term": {"user.username.keyword": user}})
    if target_index:
        filters.append({"term": {"index.keyword": target_index}})
    if outcome:
        filters.append({"term": {"outcome.keyword": outcome}})

    body = {
        "size": size,
        "from": offset,
        "sort": [{"@timestamp": {"order": "desc"}}],
        "query": {"bool": {"filter": filters}},
        # Summary over the WHOLE filtered set, not the page. The UI draws call
        # volume, outcome mix and latency from this; computing it from the 50
        # rows on screen would label "the last page" as "today".
        "aggs": {
            "over_time": {
                "date_histogram": {
                    "field": "@timestamp",
                    "fixed_interval": _histogram_interval(from_ts, to_ts),
                    "min_doc_count": 0,
                    # Without bounds a histogram spans first hit to last hit, so
                    # one busy minute in a 24h window draws a single dot instead
                    # of a line across a quiet day.
                    "extended_bounds": {
                        "min": from_ts or "now-24h",
                        "max": to_ts or "now",
                    },
                },
                "aggs": {"failed": {"filter": {"term": {"outcome.keyword": "error"}}}},
            },
            "by_action": {"terms": {"field": "action.keyword", "size": 20}},
            "by_outcome": {"terms": {"field": "outcome.keyword", "size": 10}},
            "by_user": {"terms": {"field": "user.username.keyword", "size": 10}},
            "duration": {"percentiles": {"field": "duration_ms", "percents": [50, 95]}},
        },
    }
    # Match the bare audit index AND any dated/rollover variant. write_event()
    # writes to the bare name (`.rst_copilot_audit`); "-*" alone would miss it.
    audit_index = audit.index_name() + "*"
    audit_enabled = audit.is_enabled()
    try:
        es = get_es()
        resp = await es.search(index=audit_index, body=body)
        b = resp.body or {}
    except Exception as e:
        # Audit index may not exist yet (audit disabled or no events) — return empty.
        # `audit_enabled` lets the UI tell "audit is off" from "on but no events".
        if "index_not_found" in str(e).lower():
            return {
                "total": 0,
                "events": [],
                "summary": _empty_audit_summary(),
                "audit_index": audit_index,
                "audit_enabled": audit_enabled,
            }
        raise ApiError("es_audit_query_failed", 502, reason=e)

    total = (b.get("hits") or {}).get("total") or {}
    total_value = total.get("value", 0) if isinstance(total, dict) else int(total or 0)
    events = [h.get("_source", {}) for h in (b.get("hits") or {}).get("hits", [])]
    return {
        "total": total_value,
        "events": events,
        "summary": _audit_summary(b.get("aggregations") or {}),
        "audit_index": audit_index,
        "audit_enabled": audit_enabled,
    }


def _histogram_interval(from_ts: str | None, to_ts: str | None) -> str:
    """Bucket width for the requested window.

    One fixed width cannot serve both ends of this page: hourly buckets turn a
    1h window into a single column, and a 7d window into 168 of them. Falls back
    to hourly when either end is absent or unparseable — the default window is
    24h, which is what hourly is for.
    """
    from datetime import datetime, timezone

    def _parse(v: str | None) -> datetime | None:
        if not v:
            return None
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

    lo = _parse(from_ts)
    hi = _parse(to_ts) or datetime.now(timezone.utc)
    if lo is None:
        return "1h"
    hours = (hi - lo).total_seconds() / 3600
    if hours <= 0:
        return "1h"
    if hours <= 3:
        return "5m"
    if hours <= 48:
        return "1h"
    return "1d"


def _empty_audit_summary() -> dict:
    return {
        "over_time": [],
        "by_action": [],
        "by_outcome": [],
        "by_user": [],
        "duration_p50_ms": None,
        "duration_p95_ms": None,
    }


def _audit_summary(aggs: dict) -> dict:
    """Flatten the audit aggregations into the shape the page draws.

    Percentiles come back keyed by the percent as a STRING with ES's own
    formatting ("50.0"), and are null when no document in the window carried a
    duration — a filter that matches only failures, for instance. Both are
    passed through as-is rather than defaulted to 0: "no timing recorded" and
    "0 ms" are different answers, and a chart must not draw the first as the
    second.
    """
    def buckets(name: str) -> list[dict]:
        return [
            {"key": b.get("key_as_string") or b.get("key"), "count": b.get("doc_count", 0)}
            for b in (aggs.get(name) or {}).get("buckets", [])
        ]

    over_time = [
        {
            "ts": b.get("key_as_string") or b.get("key"),
            "count": b.get("doc_count", 0),
            "failed": (b.get("failed") or {}).get("doc_count", 0),
        }
        for b in (aggs.get("over_time") or {}).get("buckets", [])
    ]
    pct = (aggs.get("duration") or {}).get("values") or {}
    return {
        "over_time": over_time,
        "by_action": buckets("by_action"),
        "by_outcome": buckets("by_outcome"),
        "by_user": buckets("by_user"),
        "duration_p50_ms": pct.get("50.0"),
        "duration_p95_ms": pct.get("95.0"),
    }


# ─────────────────────────── /api/conversations list (Round 6) ───────────────────────────


@app.get("/api/conversations")
async def list_conversations_endpoint(request: Request, limit: int = 30, offset: int = 0):
    if limit <= 0 or limit > 200:
        raise ApiError("limit_out_of_range")
    if offset < 0:
        raise ApiError("offset_negative")
    return await conversation.list_all(limit=limit, offset=offset, owner=_conv_owner(request))


# ─────────────────────────── /api/feedback/failed-cases (Round 6) ───────────────────────────


@app.get("/api/feedback/failed-cases")
async def list_failed_cases_endpoint(request: Request, limit: int = 50, offset: int = 0):
    require_admin(request)
    async with _FAILED_CASES_LOCK:
        data = _load_failed_cases()
    cases = data.get("cases") or []
    # Newest last in the file (we append) — return in reverse for UI.
    rev = list(reversed(cases))
    page = rev[offset : offset + limit]
    return {"total": len(cases), "cases": page}


@app.delete("/api/feedback/failed-cases/{idx}")
async def delete_failed_case_endpoint(idx: int, request: Request):
    require_admin(request)
    async with _FAILED_CASES_LOCK:
        data = _load_failed_cases()
        cases = data.get("cases") or []
        # Idx is in the reversed (UI) order; map back.
        real_idx = len(cases) - 1 - idx
        if real_idx < 0 or real_idx >= len(cases):
            raise ApiError("failed_case_not_found", 404, idx=idx)
        cases.pop(real_idx)
        data["cases"] = cases
        try:
            _atomic_write_yaml(data)
        except Exception as e:  # noqa: BLE001
            raise ApiError("persist_failed", 500, reason=e)
        return {"ok": True, "remaining": len(cases)}


# ─────────────────────────── /api/dashboards (Round 6) ───────────────────────────


@app.get("/api/dashboards")
async def list_dashboards():
    return {"panels": gw_dashboards.load()}


@app.post("/api/dashboards")
async def save_dashboards(req: dict, request: Request):
    require_admin(request)
    panels = req.get("panels")
    if not isinstance(panels, list):
        raise ApiError("panels_required")
    try:
        return {"panels": gw_dashboards.save(panels)}
    except ApiError:
        raise
    except ValueError as e:
        raise ApiError("invalid_request", reason=e)


# ─────────────────────────── /api/state (Wave 2 — per-owner state) ───────────────────────────
#
# Generic durable store for UI state that used to live in localStorage: triage
# disposition (team-shared), query history, UI prefs, saved queries. Kind decides
# the owner bucket (see user_state.owner_for). ES write perms required; failures
# surface a friendly error and the frontend falls back to localStorage.


def _check_kind(kind: str) -> None:
    if kind not in user_state.ALLOWED_KINDS:
        raise ApiError(
            "state_kind_unknown",
            kind=kind,
            allowed=", ".join(sorted(user_state.ALLOWED_KINDS)),
        )


@app.get("/api/state/{kind}")
async def list_state(kind: str, request: Request):
    _check_kind(kind)
    owner = user_state.owner_for(kind, current_user(request))
    try:
        items = await user_state.list_items(owner, kind)
    except Exception as e:  # noqa: BLE001
        raise es_api_error(e)
    return {"items": items}


@app.get("/api/state/{kind}/{key}")
async def get_state(kind: str, key: str, request: Request):
    _check_kind(kind)
    owner = user_state.owner_for(kind, current_user(request))
    try:
        value = await user_state.get(owner, kind, key)
    except Exception as e:  # noqa: BLE001
        raise es_api_error(e)
    return {"key": key, "value": value}


@app.put("/api/state/{kind}/{key}")
async def put_state(kind: str, key: str, request: Request):
    _check_kind(kind)
    user = current_user(request)
    owner = user_state.owner_for(kind, user)
    updated_by = (user or {}).get("username") if user else None
    try:
        value = await request.json()
    except Exception:
        raise ApiError("body_not_json")
    try:
        await user_state.put(owner, kind, key, value, updated_by)
    except Exception as e:  # noqa: BLE001
        raise es_api_error(e)
    return {"ok": True}


@app.delete("/api/state/{kind}/{key}")
async def delete_state(kind: str, key: str, request: Request):
    _check_kind(kind)
    owner = user_state.owner_for(kind, current_user(request))
    try:
        ok = await user_state.delete(owner, kind, key)
    except Exception as e:  # noqa: BLE001
        raise es_api_error(e)
    return {"ok": ok}


# ─────────────────────────── /api/reports/generate (Round 6) ───────────────────────────


@llm_post("/api/reports/generate", rpm_env="RST_RATELIMIT_REPORTS_GENERATE", rpm=6.0)
async def generate_report_endpoint(req: ReportRequest, request: Request):
    require_admin(request)

    # 时间解析放在 try 外面：放进去的话它抛的 400 会被下面那个兜底的
    # `except Exception` 抓住，再包成一句「report generation failed: 400: …」，
    # 客户看到的就是一个假的 500。
    def _parse(v: str | None, what: str) -> datetime | None:
        if not v:
            return None
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ApiError("invalid_time", what=what, value=repr(v))

    start_at, end_at = _parse(req.start, "start"), _parse(req.end, "end")
    try:
        return await gw_reports.generate(period=req.period, start=start_at, end=end_at)
    except ApiError:
        raise
    except ValueError as e:
        raise ApiError("invalid_request", reason=e)
    except Exception as e:  # noqa: BLE001
        raise ApiError("report_generation_failed", 500, reason=e)


@app.get("/api/reports/history")
async def reports_history_endpoint(request: Request, period: str | None = None, limit: int = 30):
    """Reports produced by the automated scheduler (archived in ES)."""
    require_admin(request)
    return {"reports": await report_scheduler.list_archived(period, limit)}


# ─────────────────────── /api/admin/content (signed content packs) ───────────────────────
# Online prompt / template delivery. Packs are RSA-PSS signed (license wire
# format); apply/rollback are admin-gated, verified fail-closed, and audited.


@app.get("/api/admin/content/status")
async def content_status_endpoint(request: Request):
    require_admin(request)
    return content_store.status()


@app.post("/api/admin/content/import")
async def content_import_endpoint(req: dict, request: Request):
    require_admin(request)
    token = (req.get("token") or "").strip()
    if not token:
        raise ApiError("content_token_required")
    user = current_user(request)
    actor = ((user or {}).get("username") if user else None) or "admin"
    try:
        st = content_store.apply(token, actor=actor, source="offline")
    except LicenseError as e:
        # Verification / version / compatibility rejection — a client problem.
        raise ApiError("content_pack_rejected", reason=e)
    except Exception as e:  # noqa: BLE001
        # Internal failure (e.g. disk write) — not the pack's fault; 500 so it
        # isn't mislabeled to the admin as "pack rejected".
        raise ApiError("content_pack_apply_failed", 500, reason=e)
    audit.fire_and_forget(audit.write_event(
        "content_apply", user=user, extra={"version": st.get("active_version"), "source": "offline"}
    ))
    return st


# ─────────────────────── /api/admin/enrichment (asset/identity CSV) ───────────────────────


async def _import_enrichment_csv(request: Request, kind: str) -> dict[str, Any]:
    require_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise ApiError("body_not_json")
    text = body.get("csv") if isinstance(body, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise ApiError("csv_text_missing")
    try:
        return await csv_import.import_csv(text, kind, get_es())
    except csv_import.CsvImportError as e:
        raise ApiError("csv_import_failed", reason=e)
    except Exception as e:  # noqa: BLE001
        raise ApiError("import_failed", 502, reason=str(e)[:200])


@app.post("/api/admin/enrichment/assets")
async def admin_enrichment_assets(request: Request) -> dict[str, Any]:
    return await _import_enrichment_csv(request, "assets")


@app.post("/api/admin/enrichment/identities")
async def admin_enrichment_identities(request: Request) -> dict[str, Any]:
    return await _import_enrichment_csv(request, "identities")


@app.get("/api/admin/enrichment/status")
async def admin_enrichment_status(request: Request) -> dict[str, Any]:
    require_admin(request)
    return {"sources": enrich_probe.status()}


@app.get("/api/admin/enrichment/summary")
async def admin_enrichment_summary(request: Request) -> dict[str, Any]:
    """两张表各多少行 + 「最近的告警里有多少匹配上了」。

    覆盖率是导完 CSV 之后唯一真正想知道的数：导进去了不等于用上了（列写错、主机名
    带域名后缀、IP 是动态的，都会让匹配为 0 而界面上一切正常）。
    """
    require_admin(request)
    from .enrich import inventory

    return await inventory.summary(get_es())


@app.get("/api/admin/enrichment/entries")
async def admin_enrichment_entries(
    request: Request,
    kind: str = "assets",
    q: str | None = None,
    limit: int = 50,
    after: int = 0,
) -> dict[str, Any]:
    require_admin(request)
    from .enrich import inventory

    try:
        return await inventory.list_entries(kind, q, limit, after, get_es())
    except ApiError:
        raise
    except ValueError as e:
        raise ApiError("invalid_request", reason=e)


@app.post("/api/admin/content/rollback/{version}")
async def content_rollback_endpoint(version: str, request: Request):
    require_admin(request)
    user = current_user(request)
    actor = ((user or {}).get("username") if user else None) or "admin"
    try:
        st = content_store.rollback(version, actor=actor)
    except LicenseError as e:
        # Version not in archive / anti-rollback — a client problem.
        raise ApiError("rollback_failed", reason=e)
    except Exception as e:  # noqa: BLE001
        raise ApiError("rollback_server_error", 500, reason=e)
    audit.fire_and_forget(audit.write_event(
        "content_rollback", user=user, extra={"version": version}
    ))
    return st


# ─────────────────────── /api/admin/release (image/artifact updates) ───────────────────────
# Online image delivery (P3). The gateway surfaces a newer release from its
# heartbeat; an auditor triggers the download, which verifies the signed
# manifest + every artifact sha256 and stages them (install is rst-update.sh).


@app.get("/api/admin/release/status")
async def release_status_endpoint(request: Request):
    require_admin(request)
    st = release_store.status()
    # What the license server is currently offering (from the last heartbeat).
    st["available"] = ls.get_available_release()
    # 「已是最新」只有在真的问过更新源之后才成立。没激活 / 一次心跳都没成功过的
    # 网关根本没和任何更新源通过话 —— 冷装机第一天就显示「已是最新」是误导。
    st["checked"] = ls.get_state().get("last_heartbeat_ok_at") is not None
    return st


@app.post("/api/admin/release/download")
async def release_download_endpoint(request: Request):
    require_admin(request)
    release = ls.get_available_release()
    if not release:
        raise ApiError("no_release_to_download")
    user = current_user(request)
    try:
        st = await asyncio.to_thread(
            lambda: release_store.download_and_stage(
                release, on_verify_failed=ls.report_release_verify_failed))
    except release_store.ReleaseError as e:
        # Manifest rejected / sha mismatch / disk / updater-too-old — the
        # download failed cleanly and nothing was installed.
        raise ApiError("release_download_failed", reason=e)
    except Exception as e:  # noqa: BLE001
        raise ApiError("release_download_server_error", 500, reason=e)
    audit.fire_and_forget(audit.write_event(
        "release_staged", user=user, extra={"version": st.get("staged_version")}
    ))
    return st


# ─────────────────────────── /api/engines (Round 9-C) ───────────────────────────


@app.get("/api/engines")
async def list_engines():
    """List supported SIEM backend engines + which one is active.

    Phase 0 only ships the `elastic` adapter; the others are placeholders
    so the UI can show the multi-platform story without the backend actually
    supporting them yet.
    """
    active = backend_adapter.get_adapter()
    return {
        "active": active.engine,
        "query_language": active.query_language,
        "engines": [
            {
                "id": eid,
                "label": backend_adapter.ENGINE_LABELS[eid],
                "status": backend_adapter.ENGINE_STATUS[eid],
            }
            for eid in backend_adapter.ENGINES
        ],
    }


# ─────────────────────────── /api/settings (Round 5) ───────────────────────────


@app.get("/api/settings")
async def get_settings(request: Request):
    """Effective gateway settings; sensitive values masked.

    读也要管理员。POST 早就有 require_admin，GET 一直没有 —— 于是「管理员才能
    写的配置，只读角色能读」。里面有 audit.webhook_url 这类对 Slack / 飞书 /
    企业微信来说 URL 本身即凭据的值，以及 ES 的地址和用户名。
    """
    require_admin(request)
    return {"settings": gw_settings.snapshot(mask_sensitive=True)}


@app.post("/api/settings")
async def save_settings(req: dict, request: Request):
    """Save settings → write yaml → patch os.environ → reset modules.

    Requires admin auth (RST_ADMIN_TOKEN or localhost in dev mode) — these
    settings (audit sinks, masking mode, index whitelist) are security-
    sensitive and shouldn't be reachable from arbitrary network clients.

    Body shape: flat keys (audit.enabled) or nested ({audit: {enabled: true}}).
    Sensitive sentinel values <set · N chars> are ignored.
    """
    require_admin(request)
    if not isinstance(req, dict) or not req:
        raise ApiError("body_empty")

    # Audited BEFORE the change, not after, and that ordering is the point:
    # audit.enabled and audit.webhook_url are themselves settings, so a save
    # that switches auditing off would have nowhere to report itself once it
    # had been applied. Writing first means the disable is recorded by the sink
    # it disables. Key NAMES only — the values include secrets.
    keys = gw_settings.changed_keys(req)
    user = current_user(request)
    await audit.write_event("settings.save", user=user, extra={"keys": keys})
    try:
        new_state = gw_settings.save(req)
    except ApiError:
        raise
    except ValueError as e:
        await audit.write_event(
            "settings.save", user=user, outcome="failure", error=str(e), extra={"keys": keys}
        )
        raise ApiError("invalid_request", reason=e)
    except Exception as e:  # noqa: BLE001
        await audit.write_event(
            "settings.save", user=user, outcome="failure", error=str(e), extra={"keys": keys}
        )
        raise ApiError("save_failed", 500, reason=e)

    # Re-pointing at another cluster invalidates everything that was probed or
    # seeded against the old one. Running it here is what lets a fresh install
    # be finished entirely from the browser — no container restart.
    if any(k.startswith("es.") for k in keys):
        await bootstrap_es_dependents()
    return {"settings": new_state}


@app.post("/api/settings/es/test")
async def test_es_connection(req: dict, request: Request):
    """Dial a candidate ES cluster without saving anything.

    The settings UI calls this before POST /api/settings. Saving an unreachable
    URL would take down every ES-backed page *including* the settings page the
    admin needs to undo it with, so the connection is proven first.

    Blank / omitted fields fall back to what is configured now, and the
    `<set · N chars>` sentinel means "keep the stored password" — so an admin
    can re-test an existing connection without retyping the credentials.

    No `require_admin`: dialing a cluster persists nothing, and refusing the
    probe to non-admins only means "you may not find out whether the address
    you were given works". The write that follows it (POST /api/settings) is
    still admin-only, so the settings page's read gate is what actually keeps
    the stored URL and username out of a non-admin's hands.
    """
    if not isinstance(req, dict):
        raise ApiError("body_empty")

    def _opt(key: str) -> str | None:
        v = req.get(key)
        if not isinstance(v, str) or not v.strip():
            return None
        v = v.strip()
        if v.startswith("<set ·") and v.endswith("chars>"):
            return None  # untouched sensitive field → keep the stored value
        return v

    verify = req.get("verify_certs")
    client = build_es_client(
        url=_opt("url"),
        user=_opt("user"),
        password=_opt("password"),
        verify_certs=bool(verify) if isinstance(verify, bool) else None,
        ca_cert=_opt("ca_cert"),
    )
    try:
        info = (await client.info()).body
        # Write permission is the difference between "works" and "works, but
        # triage marks and audit events silently vanish" — worth knowing during
        # setup rather than a week later.
        try:
            await client.indices.get(index="*", expand_wildcards="open", allow_no_indices=True)
            can_read = True
        except Exception:  # noqa: BLE001
            can_read = False
        return {
            "ok": True,
            "cluster_name": info.get("cluster_name"),
            "version": (info.get("version") or {}).get("number"),
            "can_list_indices": can_read,
        }
    except Exception as e:  # noqa: BLE001
        # 这条不是抛给路由的，是拼进 /api/settings/es/test 的返回体，所以要文案不要异常。
        err = es_api_error(e)
        return {"ok": False, "status": err.status_code, "error": err.detail}
    finally:
        await client.close()


# ─────────────────────────── /api/license/quota (Round 5) ───────────────────────────


@app.get("/api/license/quota")
async def license_quota():
    """Daily trial quota — only meaningful when status=unactivated.

    「今日」按部署所在时区算（`RST_TIMEZONE`），和扣额度那边同一个函数 ——
    界面上写的是「每天 N 次」，UTC 的每天不是 UTC+8 客户的每天。
    """
    today = ls._quota_day()  # type: ignore[attr-defined]
    used = ls._unactivated_calls.get(today, 0)  # type: ignore[attr-defined]
    limit = ls.TRIAL_DAILY_LIMIT
    tz = gw_settings.product_tz()
    # `reset_at_utc` 的语义不变（UTC 挂钟上的那个时刻），只是现在它跟着部署时区走：
    # +08:00 的部署在 16:00 UTC 换日。老客户端照读这个字段，仍然是对的。
    reset_local = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "reset_at_utc": reset_local.astimezone(timezone.utc).strftime("%H:%M"),
        "reset_at_local": "00:00",
        # 操作者配的那个字符串（"+08:00" / "Asia/Shanghai" / "UTC"），不是
        # `str(tzinfo)` 出来的 "UTC+08:00" —— 界面要把它显示给人看，得跟 .env 对得上。
        "timezone": gw_settings.tz_name(),
        "active": ls.get_state().get("status") == ls.STATUS_UNACTIVATED,
    }


# ─────────────────────────── /api/indices ───────────────────────────


@app.get("/api/indices")
async def list_indices(pattern: str | None = None, include_system: bool = False):
    """List ES targets (indices, aliases, data streams) visible to the gateway.

    Returns the user-facing names — for a data stream like
    `kibana_sample_data_logs`, the underlying `.ds-...` indices are hidden.
    Filters:
      - hides system targets (starting with '.') unless include_system=true
      - hides the product's OWN storage (baseline-rules et al), which is not
        customer data and is never a sensible query / detection target
      - only returns names allowed by RST_INDEX_WHITELIST (if set)
      - optional `pattern` does a simple substring match on the name
    """
    from .es_client import get_es

    try:
        es = get_es()
        # _resolve/index gives the cleanest view of what's queryable.
        resp = await es.indices.resolve_index(name="*", expand_wildcards="open")
        body = resp.body or {}
    except Exception as e:
        raise ApiError("es_resolve_index_failed", 502, reason=e)

    # cat.indices for doc_count + store_size on the underlying indices.
    cat_by_name: dict[str, dict] = {}
    try:
        cat_resp = await es.cat.indices(
            format="json", h="index,health,status,docs.count,store.size", expand_wildcards="open,hidden"
        )
        for r in (cat_resp.body or []):
            cat_by_name[r.get("index") or ""] = r
    except Exception:
        pass

    wl = index_whitelist.get()
    owned = owned_indices.owned_index_names()
    out: list[dict] = []

    def push(name: str, kind: str, attrs: list[str], backing_indices: list[str] | None = None):
        if not name:
            return
        if not include_system and name.startswith("."):
            return
        # The product's own storage is not customer data. include_system=true
        # still reveals it, so an admin inspecting the cluster can find it.
        if not include_system and name in owned:
            return
        if not wl.is_allowed(name):
            return
        if pattern and pattern.lower() not in name.lower():
            return

        # Aggregate doc count + store size across backing indices when applicable.
        doc_count = 0
        health = "unknown"
        status = "unknown"
        targets = backing_indices or [name]
        for bi in targets:
            row = cat_by_name.get(bi) or {}
            try:
                doc_count += int(row.get("docs.count") or 0)
            except Exception:
                pass
            health = row.get("health") or health
            status = row.get("status") or status
        # store_size as raw text from the first target (already human-readable).
        store_size = (cat_by_name.get(targets[0]) or {}).get("store.size") or "—"

        out.append({
            "name": name,
            "kind": kind,                # "index" | "alias" | "data_stream"
            "attributes": attrs,
            "health": health,
            "status": status,
            "doc_count": doc_count,
            "store_size": store_size,
            "backing_indices": backing_indices or [],
        })

    for ds in body.get("data_streams", []):
        push(
            ds.get("name") or "",
            "data_stream",
            ds.get("attributes") or [],
            ds.get("backing_indices") or [],
        )
    for al in body.get("aliases", []):
        push(
            al.get("name") or "",
            "alias",
            al.get("attributes") or [],
            al.get("indices") or [],
        )
    for ix in body.get("indices", []):
        # Skip hidden indices that back a data stream — already covered above.
        attrs = ix.get("attributes") or []
        if "hidden" in attrs and ix.get("data_stream"):
            continue
        push(ix.get("name") or "", "index", attrs)

    out.sort(key=lambda x: x["name"])
    return {"total": len(out), "indices": out}


# ─────────────────────────── Field Masking ───────────────────────────


@app.get("/api/masking/info")
async def masking_info():
    """Returns the active masking mode + the modes the current license can switch to."""
    return {
        "current_mode": field_masking.current_mode(),
        "available_modes": field_masking.available_modes(),
    }


# ─────────────────────────── RAG knowledge base (v1.0.2) ───────────────────────────


app.include_router(rag_router)
app.include_router(platform_ops_router)
app.include_router(baseline_router)
app.include_router(notify_router)
app.include_router(alerts_router)


# ─────────────────────────── Static ───────────────────────────

# React + Geist UI. The legacy /static vanilla HTML was retired on 2026-04-30.
# Build with `cd poc/frontend && npm run build`. SPA deep links fall back to
# index.html so /triage etc. don't 404 on refresh.
_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _dist.is_dir():
    _assets = _dist / "assets"
    if _assets.is_dir():
        app.mount(
            "/v2/assets",
            StaticFiles(directory=str(_assets)),
            name="ui_assets",
        )

    @app.get("/", include_in_schema=False)
    async def _root_redirect():
        # Legacy "/" used to serve vanilla HTML; now redirect to the React app.
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/v2/", status_code=307)

    # Accept HEAD as well — health probes, reverse proxies and curl -I expect it
    # and return 405 on a GET-only route, which broke a few real ops setups.
    @app.api_route("/v2", methods=["GET", "HEAD"], include_in_schema=False)
    async def _v2_root():
        return FileResponse(_dist / "index.html")

    # Resolved once: every request is checked for containment against this.
    _dist_root = _dist.resolve()

    @app.api_route("/v2/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def _v2_spa(path: str):
        """Serve a built SPA asset, else index.html for client-side routing.

        SECURITY: `path` is attacker-controlled and `_dist / path` alone is an
        arbitrary file read. Two distinct escapes, both confirmed against a
        running gateway before this guard existed:

          /v2/..%2f..%2f.env                → .env  (ES_PASSWORD, LLM_API_KEY)
          /v2//etc/passwd                   → no '..' needed at all: pathlib
                                              DISCARDS the left operand when the
                                              right one is absolute, so
                                              `_dist / "/etc/passwd"` is just
                                              `/etc/passwd`.

        Starlette percent-decodes the path param, so filtering the raw string
        for ".." is not enough either. Resolve, then require containment —
        that closes traversal, absolute-path replacement, and symlinks out of
        the tree in one check. This route is not under /api/, so the shared-
        secret middleware never sees it; the guard has to live here.
        """
        candidate = (_dist / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(_dist_root):
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
