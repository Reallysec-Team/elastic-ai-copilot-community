"""Operational report generator (daily / weekly / monthly).

NOT `incident_report.py` — that one renders one alert's incident report
(`/api/report/incident`). This module and the `report_*` helpers around it are
the periodic one (`/api/reports/*`).

Aggregates audit events + license stats + LLM router health into a
structured Markdown report. Runs on demand — no scheduler in this
release. Customer admins can hit POST /api/reports/generate from the
UI; if they want recurring delivery they can wrap it in their own cron
(e.g., a small bash script that POSTs to the gateway and emails the
result).

Future: APScheduler + per-period Markdown archive in ES.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from . import audit
from . import license_state as ls
from . import llm_router
from . import report_agg
from . import report_render
from .baseline import store as _bl_store
from .es_client import get_es
from .api_errors import ApiError

logger = logging.getLogger("rst.reports")


PERIODS = {
    "daily": ("过去 24 小时", timedelta(days=1)),
    "weekly": ("过去 7 天", timedelta(days=7)),
    "monthly": ("过去 30 天", timedelta(days=30)),
}


async def generate(period: str = "daily", *, include_health: bool = False,
                   end: datetime | None = None,
                   start: datetime | None = None) -> dict[str, Any]:
    """Aggregate one report over the ``period``-long window ending at ``end``.

    ``end`` defaults to now (the on-demand case). The scheduler passes an
    explicit past instant when it catches up a boundary it missed while the
    gateway was down — without it, a report filed under Tuesday would contain
    Thursday's data.

    ``start`` 给的是任意区间（界面上的自定义时间范围）。给了它，``period`` 只用来
    决定图表的分桶粒度 —— 一个跨三十天的窗口按分钟分桶，出来的是一张画不出来的图。
    """
    if period not in PERIODS:
        raise ValueError(f"unknown period '{period}'; expected daily / weekly / monthly")

    label, delta = PERIODS[period]
    # `generated_at` is always the real wall clock — a catch-up report was in
    # fact produced now, and both the archive seed and the list view sort on it.
    # Only the aggregation WINDOW moves back.
    now = datetime.now(timezone.utc)
    window_end = end.astimezone(timezone.utc) if end else now
    if start is not None:
        window_start = start.astimezone(timezone.utc)
        if window_start >= window_end:
            raise ApiError("start_after_end")
        # 自定义区间自己报自己的标签 —— 沿用「过去 24 小时」会把一份九月三号的
        # 报告说成是过去 24 小时的，归档和投递里都是这一行字。
        label = f"{window_start:%Y-%m-%d %H:%M} → {window_end:%Y-%m-%d %H:%M}"
        # 分桶粒度按跨度选，不按 period 选。
        span = window_end - window_start
        period = "daily" if span <= timedelta(days=2) else "weekly" if span <= timedelta(days=10) else "monthly"
        start_dt = window_start
    else:
        start_dt = window_end - delta
    start = start_dt
    start_iso, end_iso = start.isoformat(), window_end.isoformat()
    es = get_es()

    alerts = await report_agg.alerts_aggregate(es, start_iso, end_iso, report_render.bucket_interval(period))
    alerts["top_entities"] = await report_agg.enrich_entities(es, alerts["top_entities"])
    analysis = await report_agg.analysis_activity(es, start.timestamp(), window_end.timestamp())
    baseline = await report_agg.baseline_compliance(_bl_store.latest_run, _bl_store.list_results)
    audit_summary = await _summarize_audit(start_iso, end_iso)

    license_state = ls.get_state()

    sev = {r["severity"]: r["count"] for r in alerts["severity"]}
    exec_kpi = {
        "alerts_total": alerts["total"],
        "high_critical": sev.get("critical", 0) + sev.get("high", 0),
        "entities": len(alerts["top_entities"]),
        "analyzed": analysis["total"],
    }

    ctx = {
        "label": label, "generated_at": now.isoformat(),
        "start_at": start_iso, "end_at": end_iso,
        "license_status": license_state.get("status"),
        "alerts": alerts, "analysis": analysis, "baseline": baseline, "audit": audit_summary,
    }
    markdown = report_render.assemble_markdown(ctx)

    # Which sources returned placeholder zeros because their fetch failed. Each
    # source degrades independently so the report never 500s; without surfacing
    # it, those zeros are indistinguishable from a genuinely quiet period.
    degraded = report_agg.collect_degraded(ctx)
    if degraded:
        logger.warning("report_degraded", extra={
            "period": period, "sources": [d["source"] for d in degraded]})

    health: dict[str, Any] | None = None
    if include_health:
        health = await health_snapshot()

    result: dict[str, Any] = {
        "period": period, "label": label, "generated_at": now.isoformat(),
        "start_at": start_iso, "end_at": end_iso, "markdown": markdown,
        "summary": {
            "exec": exec_kpi, "alerts": alerts, "analysis": analysis,
            "baseline": baseline, "audit": audit_summary,
        },
        "degraded": degraded,
        "license_status": license_state.get("status"),
    }
    if health is not None:
        result["health"] = health
    return result


async def health_snapshot() -> dict[str, Any]:
    """System-health posture for the 巡检 report — no LLM, all from in-process
    state: ES reachability, license, audit/write status, SSO posture, providers."""
    from . import preflight  # local import avoids load-order coupling
    from .es_client import ping

    try:
        es_ok = bool(await ping())
    except Exception:  # noqa: BLE001
        es_ok = False

    lic = ls.get_state()
    checks = preflight.results()
    providers = [
        {
            "id": p["id"],
            "enabled": p["enabled"],
            "total_calls": p.get("total_calls", 0),
            "total_failures": p.get("total_failures", 0),
            "last_error": (p.get("last_error") or "")[:80],
        }
        for p in llm_router.get_router().status().get("providers", [])
    ]
    return {
        "es_reachable": es_ok,
        "license_status": lic.get("status"),
        "license_type": lic.get("license_type"),
        "audit_enabled": audit.is_enabled(),
        "es_write": checks.get("es_write"),
        "sso": checks.get("sso"),
        "providers": providers,
    }


async def _summarize_audit(start_iso: str, end_iso: str) -> dict[str, Any]:
    """Aggregate the audit index for the given window. Returns zeros if the
    audit index isn't present (e.g., audit not enabled)."""
    # `name*` (no dash) matches all three audit shapes: the plain fixed index,
    # date-suffixed indices, AND the data-stream name (ILM mode). The old
    # `name + "-*"` matched NONE of them, so reports always showed 0 activity.
    base_index = audit.index_name() + "*"
    es = get_es()

    body = {
        "size": 0,
        # Without this, ES caps hits.total.value at 10000 (relation="gte"),
        # while the outcomes aggregation below counts ALL docs. For windows
        # with >10k events that made success/fail exceed `total` and pushed
        # success_rate above 100%. Force an exact total (cf. conversation._es_list_all).
        "track_total_hits": True,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": start_iso, "lte": end_iso}}}
                ]
            }
        },
        # Aggregate on .keyword subfields: audit string fields are dynamically
        # mapped as `text` (both plain index and data-stream backing), and
        # aggregating a text field fails ("fielddata is disabled") — which was
        # silently caught and made every report read 0. The default dynamic
        # mapping provides `<field>.keyword` for exactly this.
        "aggs": {
            "outcomes": {"terms": {"field": "outcome.keyword", "size": 5}},
            "by_action": {
                "terms": {"field": "action.keyword", "size": 20},
                "aggs": {
                    "outcome": {"terms": {"field": "outcome.keyword", "size": 3}},
                },
            },
            "top_indexes": {"terms": {"field": "index.keyword", "size": 10}},
            "top_users": {"terms": {"field": "user.username.keyword", "size": 10}},
            "avg_duration": {"avg": {"field": "duration_ms"}},
            "unique_users": {"cardinality": {"field": "user.username.keyword"}},
            "unique_indexes": {"cardinality": {"field": "index.keyword"}},
        },
    }

    try:
        resp = await asyncio.wait_for(
            es.search(index=base_index, body=body), report_agg.ES_TIMEOUT_S
        )
        body_resp = resp.body or {}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"audit aggregate failed: {e}")
        return _empty_summary(report_agg._reason(e))

    total = (body_resp.get("hits") or {}).get("total") or {}
    total_value = total.get("value", 0) if isinstance(total, dict) else int(total or 0)
    aggs = body_resp.get("aggregations") or {}
    success = 0
    fail = 0
    for b in (aggs.get("outcomes") or {}).get("buckets", []):
        if b.get("key") == "success":
            success = b.get("doc_count", 0)
        elif b.get("key") == "fail":
            fail = b.get("doc_count", 0)

    by_action: list[dict[str, Any]] = []
    for b in (aggs.get("by_action") or {}).get("buckets", []):
        s = 0
        f = 0
        for ob in (b.get("outcome") or {}).get("buckets", []):
            if ob.get("key") == "success":
                s = ob.get("doc_count", 0)
            elif ob.get("key") == "fail":
                f = ob.get("doc_count", 0)
        by_action.append({
            "action": b.get("key", "—"),
            "count": b.get("doc_count", 0),
            "success": s,
            "fail": f,
        })

    top_indexes = [
        {"index": b.get("key"), "count": b.get("doc_count", 0)}
        for b in (aggs.get("top_indexes") or {}).get("buckets", [])
        if b.get("key")
    ]
    top_users = [
        {"user": b.get("key"), "count": b.get("doc_count", 0)}
        for b in (aggs.get("top_users") or {}).get("buckets", [])
        if b.get("key")
    ]
    avg_duration_raw = (aggs.get("avg_duration") or {}).get("value")
    avg_duration = int(avg_duration_raw) if isinstance(avg_duration_raw, (int, float)) else None
    unique_users = (aggs.get("unique_users") or {}).get("value", 0)
    unique_indexes = (aggs.get("unique_indexes") or {}).get("value", 0)

    # Harden the rate: use the larger of the exact total and success+fail as the
    # denominator so a stale/capped total can never produce a rate >100%. Only
    # success/fail count toward the numerator (other outcomes are excluded).
    rate_total = max(total_value, success + fail)
    success_rate = (success / rate_total) if rate_total else 0.0
    success_rate = min(max(success_rate, 0.0), 1.0)  # clamp to [0,1]

    return {
        "total": total_value,
        "success": success,
        "fail": fail,
        "success_rate": success_rate,
        "unique_users": unique_users,
        "unique_indexes": unique_indexes,
        "avg_duration_ms": avg_duration,
        "by_action": by_action,
        "top_indexes": top_indexes,
        "top_users": top_users,
        "degraded": None,
    }


def _empty_summary(degraded: str | None = None) -> dict[str, Any]:
    return {
        "total": 0,
        "success": 0,
        "fail": 0,
        "success_rate": 0.0,
        "unique_users": 0,
        "unique_indexes": 0,
        "avg_duration_ms": None,
        "by_action": [],
        "top_indexes": [],
        "top_users": [],
        "degraded": degraded,
    }
