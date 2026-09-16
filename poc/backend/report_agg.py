"""Security-ops report aggregations. One async function per data source; each
independently try/excepts to an empty structure so the report never 500s.

Every returned struct carries ``degraded``: None when the numbers are real, a
reason string when the source failed and the zeros are placeholders. A report
that quietly prints "本周期无告警" because ES timed out is worse than no report —
the operator reads a broken pipeline as a quiet night."""

from __future__ import annotations

import asyncio
import logging
import os

from .alerts.store import _index as _alerts_index
from .analysis_store import _index as _analysis_index

logger = logging.getLogger("rst.report_agg")

SEV_ORDER = ["critical", "high", "medium", "low", "info"]
_ENTITY_INDEX = ".entities.v1.latest.security_*"

# Per-source wall-clock budget. Without it a dead ES makes the report hang for
# tens of seconds: the transport retries with backoff on every agg call. The
# TimeoutError lands in each function's `except Exception` → empty struct, so a
# down cluster degrades to placeholders fast instead of stalling the request.
ES_TIMEOUT_S = float(os.getenv("RST_REPORT_ES_TIMEOUT_S", "5"))


#: Report source key → the name an operator sees. Also fixes the banner order.
SOURCE_LABELS = {"alerts": "告警", "analysis": "分析活动",
                 "baseline": "基线合规", "audit": "审计"}


def collect_degraded(ctx: dict) -> list[dict]:
    """The sources in ``ctx`` whose zeros are placeholders from a failed fetch.

    One derivation shared by the API payload and the rendered markdown, so the
    two cannot disagree about whether a report is trustworthy."""
    return [
        {"source": name, "reason": (ctx.get(name) or {}).get("degraded")}
        for name in SOURCE_LABELS
        if (ctx.get(name) or {}).get("degraded")
    ]


def _reason(e: Exception) -> str:
    """Short, renderable failure reason. asyncio.TimeoutError stringifies to ""."""
    return (str(e) or type(e).__name__)[:160]


def _empty_alerts(degraded: str | None = None) -> dict:
    return {
        "total": 0,
        "timeline": [],
        "by_origin": {"poll": 0, "webhook": 0},
        "severity": [{"severity": s, "count": 0, "pct": 0.0} for s in SEV_ORDER],
        "top_rules": [],
        "top_entities": [],
        "degraded": degraded,
    }


async def alerts_aggregate(es, start_iso: str, end_iso: str, interval: str) -> dict:
    body = {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"filter": [{"range": {"@timestamp": {"gte": start_iso, "lte": end_iso}}}]}},
        "aggs": {
            "timeline": {"date_histogram": {
                "field": "@timestamp", "fixed_interval": interval,
                "min_doc_count": 0, "extended_bounds": {"min": start_iso, "max": end_iso}}},
            "by_origin": {"terms": {"field": "origin", "size": 5}},
            "by_severity": {"terms": {"field": "severity", "size": 10}},
            "top_rules": {"terms": {"field": "rule_name", "size": 10},
                          "aggs": {"sev": {"terms": {"field": "severity", "size": 1}}}},
            "top_entities": {"terms": {"field": "subject_value", "size": 10},
                             "aggs": {"fld": {"terms": {"field": "subject_field", "size": 1}}}},
        },
    }
    try:
        resp = await asyncio.wait_for(es.search(index=_alerts_index(), body=body), ES_TIMEOUT_S)
        res = getattr(resp, "body", resp) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"alerts_aggregate failed: {e}")
        return _empty_alerts(_reason(e))

    total_obj = (res.get("hits") or {}).get("total") or {}
    total = total_obj.get("value", 0) if isinstance(total_obj, dict) else int(total_obj or 0)
    aggs = res.get("aggregations") or {}

    timeline = [
        {"ts": b.get("key_as_string"), "count": b.get("doc_count", 0)}
        for b in (aggs.get("timeline") or {}).get("buckets", [])
    ]

    origin_raw = {b.get("key"): b.get("doc_count", 0)
                  for b in (aggs.get("by_origin") or {}).get("buckets", [])}
    by_origin = {"poll": origin_raw.get("poll", 0), "webhook": origin_raw.get("webhook", 0)}

    sev_raw = {b.get("key"): b.get("doc_count", 0)
               for b in (aggs.get("by_severity") or {}).get("buckets", [])}
    severity = []
    for s in SEV_ORDER:
        c = sev_raw.get(s, 0)
        pct = round((c / total) * 100, 1) if total else 0.0
        severity.append({"severity": s, "count": c, "pct": pct})

    def _mode(sub: dict) -> str:
        buckets = (sub or {}).get("buckets", [])
        return buckets[0].get("key") if buckets else ""

    top_rules = [
        {"rule_name": b.get("key"), "count": b.get("doc_count", 0), "severity": _mode(b.get("sev"))}
        for b in (aggs.get("top_rules") or {}).get("buckets", []) if b.get("key")
    ]
    top_entities = [
        {"value": b.get("key"), "field": _mode(b.get("fld")), "count": b.get("doc_count", 0)}
        for b in (aggs.get("top_entities") or {}).get("buckets", []) if b.get("key")
    ]

    return {
        "total": total,
        "timeline": timeline,
        "by_origin": by_origin,
        "severity": severity,
        "top_rules": top_rules,
        "top_entities": top_entities,
        "degraded": None,
    }


def _entity_kind_field(subject_field: str) -> str | None:
    """Map an alert subject_field to the entity-store lookup field. Only hosts
    and users resolve; ip / process return None (entity store keys by name)."""
    f = subject_field or ""
    if f.startswith("host."):
        return "host.name"
    if f.startswith("user."):
        return "user.name"
    return None


async def _lookup_asset(es, field: str, value: str) -> dict | None:
    try:
        resp = await es.search(index=_ENTITY_INDEX,
                               body={"size": 1, "query": {"terms": {field: [value]}}})
        res = getattr(resp, "body", resp) or {}
    except Exception as e:  # noqa: BLE001 — best-effort, never break the report
        logger.debug(f"asset lookup failed: {e}")
        return None
    hits = ((res.get("hits") or {}).get("hits")) or []
    if not hits:
        return None
    return (hits[0].get("_source") or {}).get("asset") or None


async def _fill_assets(es, rows: list[dict]) -> None:
    """Fill asset fields in place. One ES lookup per host/user entity."""
    for row in rows:
        field = _entity_kind_field(row.get("field", ""))
        if not field:
            continue
        asset = await _lookup_asset(es, field, str(row.get("value", "")))
        if asset:
            row["business_name"] = asset.get("name")
            row["criticality"] = asset.get("criticality")
            row["owner"] = asset.get("owner")


async def enrich_entities(es, entities: list[dict]) -> list[dict]:
    out = [{**e, "business_name": None, "criticality": None, "owner": None} for e in entities]
    # One budget for the whole lookup phase, not per entity — a dead entity store
    # would otherwise cost ES_TIMEOUT_S × len(entities). Rows filled before the
    # deadline keep their asset data; the rest stay None (enrichment is best-effort).
    try:
        await asyncio.wait_for(_fill_assets(es, out), ES_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 — never break the report
        logger.debug(f"entity enrichment degraded: {e}")
    return out


def _empty_analysis(degraded: str | None = None) -> dict:
    return {"total": 0, "by_kind": {"triage": 0, "investigation": 0},
            "high_ratio": 0.0, "top_topics": [], "degraded": degraded}


async def analysis_activity(es, start_epoch: float, end_epoch: float) -> dict:
    body = {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"filter": [
            {"range": {"created_at": {"gte": start_epoch, "lte": end_epoch}}}]}},
        "aggs": {
            "by_kind": {"terms": {"field": "kind.keyword", "size": 5}},
            "by_sev": {"terms": {"field": "severity.keyword", "size": 10}},
            "top_topics": {"terms": {"field": "title.keyword", "size": 5}},
        },
    }
    try:
        resp = await asyncio.wait_for(es.search(index=_analysis_index(), body=body), ES_TIMEOUT_S)
        res = getattr(resp, "body", resp) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"analysis_activity failed: {e}")
        return _empty_analysis(_reason(e))

    total_obj = (res.get("hits") or {}).get("total") or {}
    total = total_obj.get("value", 0) if isinstance(total_obj, dict) else int(total_obj or 0)
    aggs = res.get("aggregations") or {}

    kind_raw = {b.get("key"): b.get("doc_count", 0)
                for b in (aggs.get("by_kind") or {}).get("buckets", [])}
    by_kind = {"triage": kind_raw.get("triage", 0), "investigation": kind_raw.get("investigation", 0)}

    high = sum(b.get("doc_count", 0) for b in (aggs.get("by_sev") or {}).get("buckets", [])
               if b.get("key") in ("high", "critical"))
    high_ratio = round(high / total, 2) if total else 0.0

    top_topics = [b.get("key") for b in (aggs.get("top_topics") or {}).get("buckets", []) if b.get("key")]

    return {"total": total, "by_kind": by_kind, "high_ratio": high_ratio,
            "top_topics": top_topics, "degraded": None}


def _empty_baseline(degraded: str | None = None) -> dict:
    return {"run_at": None, "pass_rate": None, "by_verdict": {}, "top_fails": [],
            "degraded": degraded}


async def baseline_compliance(latest_run, list_results) -> dict:
    """`latest_run` / `list_results` are async callables (injected for tests;
    production binds baseline.store.latest_run / .list_results)."""
    try:
        run = await asyncio.wait_for(latest_run(), ES_TIMEOUT_S)
        if not run:
            return _empty_baseline()  # genuinely never run — not a degradation
        run_id = run.get("run_id")
        results = await asyncio.wait_for(list_results(run_id=run_id), ES_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"baseline_compliance failed: {e}")
        return _empty_baseline(_reason(e))

    by_verdict: dict[str, int] = {}
    fails: list[dict] = []
    for r in results or []:
        v = str(r.get("verdict") or "unknown")
        by_verdict[v] = by_verdict.get(v, 0) + 1
        if v != "pass":
            fails.append({"rule_id": r.get("rule_id"), "host": r.get("host"),
                          "severity": r.get("severity") or "info"})

    # Rate from the RUN's own counters, not from `results`. `list_results`
    # defaults to size=1000 and the shipped pack is 127 rules, so at 8 hosts
    # (1016 docs) the fetch truncates — and every result in a run carries the
    # same `checked_at`, so which 1000 survive is an undefined ES tiebreak. The
    # report's 合规达标率 then disagreed with the baseline page's scorecard,
    # which computes from the full counts, and the report's number was the wrong
    # one. `results` is still the right source for the top-fails SAMPLE.
    run_pass = run.get("pass")
    run_fail = run.get("fail")
    if isinstance(run_pass, int) and isinstance(run_fail, int) and (run_pass + run_fail) > 0:
        total = run_pass + run_fail
        passed = run_pass
        pass_rate = round(passed / total * 100, 1)
    else:
        total = sum(by_verdict.values())
        passed = by_verdict.get("pass", 0)
        # None, not 100: "nothing evaluable" is not "everything passed".
        pass_rate = round((passed / total) * 100, 1) if total else None

    def _sev_key(f: dict) -> int:
        s = f.get("severity")
        return SEV_ORDER.index(s) if s in SEV_ORDER else len(SEV_ORDER)

    fails.sort(key=_sev_key)
    return {"run_at": run.get("finished_at"), "pass_rate": pass_rate,
            "by_verdict": by_verdict, "top_fails": fails[:10], "degraded": None}
