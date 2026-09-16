"""Unified alert store — normalizes Kibana/ES detection alerts into one shape and
persists them (deduped) to ``.rst_copilot_alerts``.

Handles both index layouts:
  - 8.x ``.alerts-security.alerts-*``  (kibana.alert.* fields)
  - 7.x ``.siem-signals-*``            (signal.* fields)
plus a generic fallback. Raw source is kept for fidelity; masking is applied only
at external egress (Feishu card / LLM), never here.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from ..es_client import get_es

logger = logging.getLogger("rst.alerts.store")

DEFAULT_INDEX = ".rst_copilot_alerts"
_SEVERITIES = {"info", "low", "medium", "high", "critical"}
_index_ready = False


def _index() -> str:
    return (os.environ.get("RST_ALERTS_STORE_INDEX") or DEFAULT_INDEX).strip() or DEFAULT_INDEX


def dig(src: dict, *paths: str) -> Any:
    """First non-empty value among dotted paths (also tries the flattened key)."""
    for path in paths:
        # nested walk
        cur: Any = src
        ok = True
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur not in (None, "", []):
            return cur
        # flattened key (ES often stores "kibana.alert.severity" verbatim)
        if src.get(path) not in (None, "", []):
            return src.get(path)
    return None


def _norm_severity(raw: Any) -> str:
    s = str(raw or "").lower()
    if s in _SEVERITIES:
        return s
    # numeric risk score fallback (0-100)
    try:
        score = float(raw)
        if score >= 90:
            return "critical"
        if score >= 70:
            return "high"
        if score >= 40:
            return "medium"
        if score > 0:
            return "low"
    except (TypeError, ValueError):
        pass
    return "info"


def normalize(source: dict[str, Any], *, doc_id: str | None = None, origin: str = "poll",
              source_index: str | None = None, source_id: str | None = None) -> dict[str, Any]:
    """Map a raw Kibana/ES alert doc to the product's unified alert shape.

    ``source_index`` / ``source_id`` capture where the alert lives in the customer
    ES so the UI can deep-link back to Kibana. Source B (webhook) may carry them in
    the payload (``_index`` / ``_id``); fall back to those when not passed."""
    alert_id = dig(source, "kibana.alert.uuid", "signal.group.id", "event.id") or doc_id or ""
    rule_name = dig(source, "kibana.alert.rule.name", "signal.rule.name", "rule.name") or "未命名规则"
    rule_id = dig(source, "kibana.alert.rule.uuid", "kibana.alert.rule.rule_id",
                   "signal.rule.id", "rule.id") or ""
    severity = _norm_severity(
        dig(source, "kibana.alert.severity", "signal.rule.severity", "event.severity",
             "kibana.alert.risk_score", "signal.rule.risk_score"))
    ts = dig(source, "@timestamp", "kibana.alert.original_time", "signal.original_time") \
        or datetime.now(timezone.utc).isoformat()
    subject_field, subject_value = _guess_subject(source)

    return {
        "alert_id": str(alert_id),
        "rule_id": str(rule_id),
        "rule_name": str(rule_name),
        "severity": severity,
        "@timestamp": ts,
        "subject_field": subject_field,
        "subject_value": subject_value,
        "origin": origin,  # poll | webhook
        "source_index": source_index or dig(source, "_index") or "",
        "source_id": source_id or dig(source, "_id") or "",
        "summary": "",  # filled by summarize() in handle_new_alert
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "raw": source,
    }


_SUBJECT_FIELDS = ("host.name", "host.hostname", "source.ip", "user.name",
                   "client.ip", "destination.ip", "process.name")


def _guess_subject(source: dict[str, Any]) -> tuple[str | None, str | None]:
    for f in _SUBJECT_FIELDS:
        v = dig(source, f)
        if v not in (None, "", []):
            return f, str(v[0] if isinstance(v, list) else v)
    return None, None


async def _ensure_index() -> None:
    global _index_ready
    if _index_ready:
        return
    es = get_es()
    try:
        if not await es.indices.exists(index=_index()):
            await es.indices.create(index=_index(), body={
                "mappings": {
                    "properties": {
                        "alert_id": {"type": "keyword"},
                        "rule_id": {"type": "keyword"},
                        "rule_name": {"type": "keyword"},
                        "severity": {"type": "keyword"},
                        "@timestamp": {"type": "date"},
                        "subject_field": {"type": "keyword"},
                        "subject_value": {"type": "keyword"},
                        "origin": {"type": "keyword"},
                        "source_index": {"type": "keyword"},
                        "source_id": {"type": "keyword"},
                        "summary": {"type": "text"},
                        # 因为超出摘要预算而没生成 —— 和「摘要关着」「本来就没主体」
                        # 要能分开，否则界面上三者长得一模一样。
                        "summary_skipped": {"type": "boolean"},
                        "ingested_at": {"type": "date"},
                        "raw": {"type": "object", "enabled": False},
                    }
                }
            })
        _index_ready = True
    except Exception as e:  # noqa: BLE001
        logger.warning("alerts_index_ensure_failed", extra={"error": str(e)})


async def store_alert(alert: dict[str, Any]) -> bool:
    """Persist deduped by ``alert_id`` (op_type=create). Returns True if new."""
    from elasticsearch import ConflictError
    await _ensure_index()
    doc_id = alert.get("alert_id") or ""
    if not doc_id:
        return False
    try:
        await get_es().index(index=_index(), id=doc_id, document=alert,
                              op_type="create", refresh=False)
        return True
    except ConflictError:
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("alert_store_failed", extra={"id": doc_id, "error": str(e)})
        return False


async def exists(alert_id: str) -> bool:
    """True if the alert is already stored.

    A cheap pre-check so ingest can skip the paid LLM summary for a duplicate.
    ``store_alert``'s op_type=create stays the authoritative dedup — a race here
    only costs one wasted summary, never a lost or duplicated alert. Errors
    answer False so an ES fault degrades to "summarize anyway", never to a drop.
    """
    if not alert_id:
        return False
    try:
        return bool(await get_es().exists(index=_index(), id=alert_id))
    except Exception:  # noqa: BLE001 — index missing / ES down
        return False


async def get_alert(alert_id: str) -> dict[str, Any] | None:
    """Full stored alert incl. ``raw`` (for the detail view). Returns None if
    missing. Unmasked — the detail view serves the operator's own UI."""
    try:
        resp = await get_es().get(index=_index(), id=alert_id)
        return resp.body.get("_source") or {}
    except Exception:  # noqa: BLE001 — not found / ES down
        return None


async def list_alerts(limit: int = 50, severity: str | None = None, *,
                      before: str | None = None, rule: str | None = None,
                      since: str | None = None, until: str | None = None) -> list[dict[str, Any]]:
    """Newest-first alerts with optional filters.

    - ``before``: @timestamp strict upper bound — the infinite-scroll cursor
      (pass the last row's @timestamp to fetch the next older page).
    - ``rule``: substring match on rule_name / rule_id.
    - ``since`` / ``until``: @timestamp range (inclusive/exclusive per ES).
    """
    es = get_es()
    must: list[dict] = []
    if severity:
        must.append({"term": {"severity": severity}})
    if rule:
        # rule_name/rule_id are keyword fields → wildcard substring (case-insensitive)
        # instead of a text match, which wouldn't tokenize a keyword.
        esc = rule.replace("*", "\\*").replace("?", "\\?")
        must.append({"bool": {"should": [
            {"wildcard": {"rule_name": {"value": f"*{esc}*", "case_insensitive": True}}},
            {"wildcard": {"rule_id": {"value": f"*{esc}*", "case_insensitive": True}}},
        ], "minimum_should_match": 1}})
    ts_range: dict[str, Any] = {}
    if before:
        ts_range["lt"] = before
    if since:
        ts_range["gte"] = since
    if until:
        ts_range["lte"] = until
    if ts_range:
        must.append({"range": {"@timestamp": ts_range}})
    try:
        resp = await es.search(index=_index(), body={
            "size": max(1, min(limit, 200)),
            "query": {"bool": {"must": must or [{"match_all": {}}]}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "_source": {"excludes": ["raw"]},
        })
    except Exception:  # noqa: BLE001
        return []
    return [h.get("_source") or {} for h in (resp.body.get("hits") or {}).get("hits") or []]


async def stats(*, rule: str | None = None, since: str | None = None,
                until: str | None = None) -> dict[str, Any]:
    """Counts over the whole filtered window, for the page's overview.

    Deliberately does NOT take `severity`. The severity breakdown is what the
    overview draws, and drawing it from a severity-filtered set would leave one
    slice at 100% — the reading would change every time the operator narrowed
    the list it is supposed to describe.

    Bucket width follows the window for the same reason it does on the audit
    page: hourly buckets draw a one-hour window as a single column.
    """
    es = get_es()
    must: list[dict] = []
    if rule:
        esc = rule.replace("*", "\\*").replace("?", "\\?")
        must.append({"bool": {"should": [
            {"wildcard": {"rule_name": {"value": f"*{esc}*", "case_insensitive": True}}},
            {"wildcard": {"rule_id": {"value": f"*{esc}*", "case_insensitive": True}}},
        ], "minimum_should_match": 1}})
    ts_range: dict[str, Any] = {}
    if since:
        ts_range["gte"] = since
    if until:
        ts_range["lte"] = until
    if ts_range:
        must.append({"range": {"@timestamp": ts_range}})

    body = {
        "size": 0,
        "query": {"bool": {"must": must or [{"match_all": {}}]}},
        "aggs": {
            "by_severity": {"terms": {"field": "severity", "size": 10}},
            # 10：安全态势那张「告警最多的规则」卡按 Top 10 展示。
            "by_rule": {"terms": {"field": "rule_name", "size": 10}},
            "over_time": {
                "date_histogram": {
                    "field": "@timestamp",
                    "fixed_interval": _histogram_interval(since, until),
                    "min_doc_count": 0,
                    "extended_bounds": {"min": since or "now-24h", "max": until or "now"},
                },
            },
        },
    }
    try:
        resp = await es.search(index=_index(), body=body)
        b = resp.body or {}
    except Exception as e:  # noqa: BLE001
        # Nothing ingested yet is the common case on a fresh install, and an
        # empty overview is the honest answer there.
        if "index_not_found" in str(e).lower():
            return {"total": 0, "by_severity": [], "by_rule": [], "over_time": []}
        # Anything else is NOT "no alerts". Swallowing it renders a working
        # cluster as a quiet one: the aggregation fails (severity mapped as
        # text by someone else's template, say) and the page reads 0 while the
        # feed below it lists fifty rows. Let the caller see the failure.
        raise

    total = (b.get("hits") or {}).get("total") or {}
    aggs = b.get("aggregations") or {}

    def _buckets(name: str) -> list[dict[str, Any]]:
        return [{"key": x.get("key"), "count": x.get("doc_count", 0)}
                for x in (aggs.get(name) or {}).get("buckets", [])]

    return {
        "total": total.get("value", 0) if isinstance(total, dict) else int(total or 0),
        "by_severity": _buckets("by_severity"),
        "by_rule": _buckets("by_rule"),
        "over_time": [
            {"ts": x.get("key_as_string") or x.get("key"), "count": x.get("doc_count", 0)}
            for x in (aggs.get("over_time") or {}).get("buckets", [])
        ],
    }


def _histogram_interval(since: str | None, until: str | None) -> str:
    """Bucket width for the requested window; hourly when it cannot be measured."""
    from datetime import datetime, timezone

    def _parse(v: str | None) -> datetime | None:
        if not v:
            return None
        try:
            d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

    lo = _parse(since)
    hi = _parse(until) or datetime.now(timezone.utc)
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
