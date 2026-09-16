"""Real-time alert API: SSE stream + Kibana webhook ingest (source B) + list.

Paths under /api/alerts/*. Source B is a shared-secret endpoint: Kibana's webhook
connector can only attach a static header, so we constant-time compare a token
(``X-RST-Alert-Token`` vs env ``RST_ALERT_WEBHOOK_SECRET``) rather than body-HMAC,
which Kibana cannot compute. The endpoint is disabled (403) until the secret is set
so ingestion is never open.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from . import index_whitelist, kibana_link, llm_cost
from .alerts import broker, ingest, store
from .enrich import resolver
from .es_client import get_es
from .api_errors import ApiError

logger = logging.getLogger("rst.alerts.routes")

router = APIRouter(tags=["alerts"])

# ingest 会花 LLM（每条告警一次 summarize），所以按 llm_cost 的规矩在路由处声明。
llm_post = llm_cost.marker(router)

_SSE_PING_SECONDS = 15.0
_MAX_INGEST_BATCH = 200


@router.get("/api/alerts")
async def list_alerts(limit: int = 50, severity: str | None = None,
                      before: str | None = None, rule: str | None = None,
                      since: str | None = None, until: str | None = None) -> dict[str, Any]:
    return {"alerts": await store.list_alerts(
        limit=limit, severity=severity, before=before, rule=rule, since=since, until=until)}


@router.get("/api/alerts/stats")
async def alerts_stats(rule: str | None = None, since: str | None = None,
                       until: str | None = None) -> dict[str, Any]:
    """Overview counts for the alert feed: severity mix, top rules, arrival rate.

    Declared before `/api/alerts/{alert_id}` — FastAPI matches in declaration
    order, and the parameterised route would otherwise swallow `stats` and look
    up an alert by that id.
    """
    try:
        return await store.stats(rule=rule, since=since, until=until)
    except Exception as e:  # noqa: BLE001
        logger.warning("alerts_stats_failed", extra={"error": str(e)})
        raise ApiError("alerts_aggregate_failed", 502, reason=e) from e


@router.get("/api/alerts/stream")
async def stream_alerts(request: Request) -> StreamingResponse:
    """SSE feed of newly ingested alerts. Values are NOT masked — this stream
    serves the operator's own UI (same trust domain), unlike the Feishu egress."""
    async def event_gen():
        q = broker.subscribe()
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    alert = await asyncio.wait_for(q.get(), timeout=_SSE_PING_SECONDS)
                    yield f"data: {json.dumps(alert, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # keep-alive comment
        finally:
            broker.unsubscribe(q)

    return StreamingResponse(event_gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # disable proxy buffering (nginx)
    })


# quota=False：这是机器路径（Kibana webhook connector），不是人点出来的生成动作。
# 扣试用额度会在额度耗尽那一刻把整个请求 402 掉 —— 那不是「少一句摘要」，是丢告警。
# 限流留着：桶按请求算，而一个请求最多带 _MAX_INGEST_BATCH 条告警，所以它封的是
# 请求速率不是 LLM 调用数；真要压 LLM 花费用 RST_ALERT_SUMMARY_MIN_SEVERITY /
# RST_ALERT_SUMMARY=0。
@llm_post("/api/alerts/ingest", quota=False, rpm=120.0,
          rpm_env="RST_RATELIMIT_ALERT_INGEST")
async def ingest_webhook(request: Request,
                         x_rst_alert_token: str | None = Header(default=None)) -> dict[str, Any]:
    """Source B — Kibana webhook connector target. Normalizes the posted signal(s),
    stores + streams + dispatches them through the shared ingest path."""
    secret = (os.environ.get("RST_ALERT_WEBHOOK_SECRET") or "").strip()
    if not secret:
        raise ApiError("alert_webhook_disabled", 403)
    if not x_rst_alert_token or not hmac.compare_digest(x_rst_alert_token, secret):
        raise ApiError("alert_webhook_token_invalid", 401)

    try:
        payload = await request.json()
    except Exception:
        raise ApiError("body_not_json")

    # Accept a single alert, {"alerts": [...]}, or a bare list.
    if isinstance(payload, dict) and isinstance(payload.get("alerts"), list):
        raw_items = payload["alerts"]
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = [payload]

    # Cap per request so a large POST can't amplify into unbounded ES writes +
    # fan-out (each item = store + publish + dispatch). Matches the poll batch.
    received = len(raw_items)
    dropped = 0
    if received > _MAX_INGEST_BATCH:
        dropped = received - _MAX_INGEST_BATCH
        raw_items = raw_items[:_MAX_INGEST_BATCH]
        logger.warning("ingest_batch_truncated", extra={"received": received, "dropped": dropped})

    malformed = sum(1 for raw in raw_items if not isinstance(raw, dict))
    items = [raw for raw in raw_items if isinstance(raw, dict)]

    deadline = time.monotonic() + ingest.summary_budget_s()
    sem = asyncio.Semaphore(ingest.summary_concurrency())
    no_summary = 0

    async def _one(raw: dict[str, Any]) -> bool:
        nonlocal no_summary
        async with sem:
            # Fallback id. The poll path always passes `doc_id=hit["_id"]`; this
            # path used to pass nothing, so an alert whose payload carried none of
            # kibana.alert.uuid / signal.group.id / event.id got alert_id="" and was
            # dropped by store_alert with NO log line — while the endpoint returned
            # 200 {"ingested":0,...}, which reads as "duplicate, already have it".
            # Since a Kibana webhook body is an operator-authored Mustache template,
            # that was 100% silent data loss for anyone whose template omitted those
            # fields. Hashing the canonical payload keeps genuine retries idempotent
            # (same body → same id → op_type=create dedups) without inventing a
            # random id that would duplicate on every retry.
            alert = store.normalize(raw, doc_id=_fallback_alert_id(raw), origin="webhook")
            in_budget = time.monotonic() < deadline
            if not in_budget:
                no_summary += 1
            return await ingest.handle_new_alert(alert, summarize=in_budget)

    # 并发有上限、摘要有时间预算：一次推送最多 200 条，每条一次 LLM 串下来能到
    # 几分钟，而 Kibana connector 到点就重发同一批 —— 整批再走一遍。
    results = await asyncio.gather(*(_one(raw) for raw in items), return_exceptions=True)
    failed = [r for r in results if isinstance(r, BaseException)]
    for e in failed:
        logger.warning("ingest_item_failed", extra={"error": str(e)[:200]})
    ingested = sum(1 for r in results if r is True)

    if malformed:
        logger.warning("ingest_malformed_items", extra={"count": malformed})
    if no_summary:
        logger.warning("ingest_summary_budget_spent",
                       extra={"without_summary": no_summary, "budget_s": ingest.summary_budget_s()})
    return {"ingested": ingested, "received": received, "dropped": dropped,
            "malformed": malformed, "failed": len(failed), "without_summary": no_summary}


def _fallback_alert_id(raw: dict[str, Any]) -> str:
    """Deterministic id for a webhook payload that carries no alert identifier."""
    canon = json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str)
    return "wh-" + hashlib.sha1(canon.encode("utf-8")).hexdigest()[:32]


@router.get("/api/alerts/ingest/status")
async def ingest_status() -> dict[str, Any]:
    """Live ingest posture for the GUI config block."""
    return await ingest.status()


# {alert_id} routes come AFTER the static /stream + /ingest paths so those aren't
# captured as an alert id.
@router.get("/api/alerts/{alert_id}/enrichment")
async def alert_enrichment(alert_id: str) -> dict[str, Any]:
    """Asset/identity context for the alert's host/user/ip entities. Unmasked —
    this serves the operator's own detail UI. None when unresolved (not an error)."""
    alert = await store.get_alert(alert_id)
    if alert is None:
        raise ApiError("alert_not_found", 404)
    raw = alert.get("raw") or alert
    ctx = await resolver.resolve(raw, get_es())
    return {"enrichment": ctx}


@router.get("/api/alerts/{alert_id}/kibana-link")
async def alert_kibana_link(alert_id: str, request: Request) -> dict[str, Any]:
    """Deep links for one alert: Kibana Discover (raw doc, filtered by uuid) +
    the Security alerts app. Discover needs a Data View for the source index."""
    alert = await store.get_alert(alert_id)
    if alert is None:
        raise ApiError("alert_not_found", 404)
    origin = kibana_link.trusted_origin(request)
    security_url = f"{kibana_link.public_kibana_url(origin)}/app/security/alerts"

    discover_url: str | None = None
    discover_error: str | None = None
    source_index = alert.get("source_index") or ""
    # source_index is not ours: store.py falls back to the posted document's
    # `_index`, so a caller holding the webhook token picks it. Every other
    # index-taking route runs the whitelist; this one did not, which made it a
    # way to have the gateway resolve Data Views for indices the operator
    # deliberately excluded.
    if source_index and not index_whitelist.get().is_allowed(source_index):
        discover_error = (
            f"来源索引 '{source_index}' 不在索引白名单内（RST_INDEX_WHITELIST），不生成 Discover 链接。"
        )
        source_index = ""
    if source_index:
        # Filter Discover by the alert id. Match EITHER kibana.alert.uuid (the
        # field name in Kibana's own .alerts-security.* index — the real target)
        # OR alert_id (the field in our own .rst_copilot_alerts store), so the
        # link resolves whether it points at the source index or the product store.
        uid = alert.get("alert_id") or alert.get("source_id")
        dsl = {"query": {"bool": {"should": [
            {"term": {"kibana.alert.uuid": uid}},
            {"term": {"alert_id": uid}},
        ], "minimum_should_match": 1}}}
        try:
            link = await kibana_link.build_kibana_link(source_index, dsl, request_origin=origin)
            discover_url = link["url"]
        except kibana_link.DataViewNotFound as e:
            discover_error = str(e)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            # A transport failure surfaced as its raw text ("All connection
            # attempts failed") tells the operator nothing they can act on.
            # Name the address we tried and the setting that controls it.
            discover_error = (
                f"无法连接 Kibana（{kibana_link.configured_kibana_url() or '未配置 KIBANA_URL'}）。"
                f"请检查 .env 中的 KIBANA_URL 是否指向可达的 Kibana，以及网络 / 证书是否正常。"
                f"（{type(e).__name__}）"
            )
        except Exception as e:  # noqa: BLE001
            discover_error = f"生成 Discover 链接失败：{str(e)[:160]}"
    else:
        # `or` guard: the whitelist rejection above also clears source_index, and
        # its reason is the more useful of the two.
        discover_error = discover_error or "该告警未记录来源索引，无法生成 Discover 链接"

    return {
        "discover_url": discover_url,
        "discover_error": discover_error,
        # 请求带了 Origin，但那不是这个网关认识的地址 —— 深链于是用的是内部主机名
        # （KIBANA_URL），浏览器多半打不开。链接照给，但界面上得说得出原因。
        "origin_ignored": kibana_link.origin_ignored(request),
        "security_url": security_url,
        "source_index": source_index,
        "source_id": alert.get("source_id") or "",
    }


@router.get("/api/alerts/{alert_id}")
async def get_alert(alert_id: str) -> dict[str, Any]:
    """Full alert incl. raw source (detail view). Unmasked (operator UI)."""
    alert = await store.get_alert(alert_id)
    if alert is None:
        raise ApiError("alert_not_found", 404)
    return alert
