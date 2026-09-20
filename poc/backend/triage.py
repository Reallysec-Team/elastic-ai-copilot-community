"""Alert batch triage: cluster pending alerts by (rule, subject), ask LLM to
score + rank + recommend per cluster, return a prioritized list.
"""

import asyncio
import json
import logging
import os
from typing import Any


from . import feature_unlock, llm_reasoning
from .es_client import get_es, es_api_error
from .field_masking import mask_doc
from .llm import parse_json
from .llm_router import get_router
from .prompts import triage_system_prompt, build_triage_prompt
from .rag import augment_prompt_meta
from .api_errors import ApiError
from .validator import validate_dsl

logger = logging.getLogger("rst.triage")

FEATURE = "alert_triage"

# SEC-CC-1: the clustering, score merge, ranking and the scoring prompt are the
# sealed core (premium/alert_triage.sealed). This file is the open shell —
# fetch, mask, call the model, assemble the response. `load_premium` raises
# FeatureLocked on a host that is not entitled; main.py turns that into 403.


def _llm_chunk_size() -> int:
    """每次送模型的聚类数。RST_TRIAGE_LLM_CHUNK,默认 4。"""
    try:
        return max(1, int(os.environ.get("RST_TRIAGE_LLM_CHUNK", "4")))
    except ValueError:
        return 4


def _llm_concurrency() -> int:
    """同时在飞的评分请求数。RST_TRIAGE_LLM_CONCURRENCY,默认 3。"""
    try:
        return max(1, int(os.environ.get("RST_TRIAGE_LLM_CONCURRENCY", "3")))
    except ValueError:
        return 3


def _core() -> dict:
    return feature_unlock.load_premium(FEATURE)


async def triage_alerts(
    alerts: list[dict[str, Any]] | None = None,
    *,
    index: str | None = None,
    query: dict[str, Any] | None = None,
    window_minutes: int = 60,
    max_alerts: int = 100,
    reasoning: str | None = None,
    max_clusters_to_llm: int = 30,
) -> dict[str, Any]:
    """Triage a batch of pending alerts. Either pass `alerts` directly, or pass
    `index` (+ optional `query` / `window_minutes`) to fetch from ES.
    """
    # window_total: how many alerts the window ACTUALLY holds, which may exceed
    # the sample we fetched. Only ES knows it; a caller passing `alerts` gives us
    # everything it has, so there the two are the same.
    window_total: int | None = None
    if alerts is None:
        if not index:
            raise ApiError("alerts_or_index_required")
        alerts, window_total = await _fetch_alerts(index, query, window_minutes, max_alerts)

    if not isinstance(alerts, list):
        raise ApiError("alerts_not_list")
    if len(alerts) > max_alerts:
        raise ApiError("too_many_alerts", n=len(alerts), cap=max_alerts)

    # Unlock BEFORE any ES or LLM spend: an unentitled host must fail here,
    # not after it has paid for the fetch.
    core = _core()
    clusters = core["cluster_alerts"](alerts)
    total_clusters = len(clusters)

    sorted_clusters = sorted(clusters, key=lambda c: c["count"], reverse=True)
    to_score = sorted_clusters[:max_clusters_to_llm]
    skipped = sorted_clusters[max_clusters_to_llm:]
    truncated = len(skipped) > 0

    sampled = len(alerts)
    total_alerts = window_total if window_total is not None else sampled
    alerts_truncated = total_alerts > sampled

    if not to_score:
        return {
            "total_alerts": total_alerts,
            "sampled_alerts": sampled,
            "alerts_truncated": alerts_truncated,
            "total_clusters": 0,
            "scored_clusters": 0,
            "truncated": False,
            "clusters": [],
            "rag_chunks_used": 0,
        }

    from .enrich.prompt_context import asset_context_block
    llm_input = []
    for c in to_score:
        payload = _cluster_to_llm_payload(c)
        try:
            payload["asset_context"] = await asset_context_block(c.get("_latest_src") or {})
        except Exception:  # noqa: BLE001 — best-effort, never break triage
            payload["asset_context"] = None
        llm_input.append(payload)
    # 一次把 30 个聚类塞给模型,耗时随聚类数线性涨(冷启动实测 ark-code-latest
    # 约 30 s / 聚类,6 个就顶到 180 s 超时,重试三次 = 9 分钟后降级)。分成小批
    # 并发打,每一批都在超时以内;哪一批失败只降级哪一批。
    chunk_size = _llm_chunk_size()
    chunks = [llm_input[i:i + chunk_size] for i in range(0, len(llm_input), chunk_size)]
    sem = asyncio.Semaphore(_llm_concurrency())

    async def _score_chunk(chunk: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], int, str | None]:
        user_prompt = build_triage_prompt(chunk)
        user_prompt, rag_used = await augment_prompt_meta(user_prompt, top_k=3)
        try:
            async with sem:
                resp, _provider = await get_router().chat_completion(
                    messages=[
                        {"role": "system", "content": triage_system_prompt()},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0,
                    # 告警分诊：固定 JSON 评分格式，low 够用（high 在 ark 上 100s+）；用户开关可覆盖
                    reasoning=llm_reasoning.from_request(reasoning, "low"),
                )
            raw = resp.choices[0].message.content or ""
            try:
                return core["index_llm_scores"](parse_json(raw)), rag_used, None
            except Exception as e:  # noqa: BLE001 — unparseable reply → this chunk degrades
                logger.warning(f"triage LLM JSON parse failed: {e}")
                return {}, rag_used, f"LLM 返回的内容无法解析为 JSON({str(e)[:120]})"
        except Exception as e:  # noqa: BLE001 — timeout / outage → this chunk degrades
            logger.warning(f"triage LLM call failed: {e}")
            msg = str(e)
            if "timed out" in msg.lower() or "timeout" in msg.lower():
                return {}, rag_used, "LLM 评分超时"
            return {}, rag_used, f"LLM 评分失败({msg[:120]})"

    # The LLM scoring step is best-effort: a timeout / outage / unparseable
    # reply must NOT discard the clustering work the analyst already paid for.
    # On failure we degrade to a volume-ranked list (severity unknown) plus a
    # `degraded` flag, so the operator still sees what's noisy and can retry.
    degraded_reason: str | None = None
    scored_by_id: dict[str, dict[str, Any]] = {}
    rag_used = 0
    failures: list[str] = []
    for scores, used, err in await asyncio.gather(*(_score_chunk(c) for c in chunks)):
        scored_by_id.update(scores)
        rag_used = max(rag_used, used)
        if err:
            failures.append(err)
    if failures:
        first = failures[0]
        if len(failures) == len(chunks):
            degraded_reason = f"{first}。以下为按告警数量排序的聚类(未含 AI 严重度/建议),可稍后重试评分。"
        else:
            degraded_reason = (
                f"{first}:{len(chunks)} 批评分里 {len(failures)} 批失败,那些聚类只按告警数量排序、"
                "未含 AI 严重度/建议,其余照常。可稍后重试。"
            )

    out_clusters = [core["merge_cluster"](c, scored_by_id.get(c["cluster_id"])) for c in to_score]
    out_clusters = core["renormalize_ranks"](out_clusters)
    out_clusters.sort(key=lambda c: c["priority_rank"])

    result: dict[str, Any] = {
        "total_alerts": total_alerts,
        # The clustering, severity split, FP estimate and ranking below describe
        # `sampled_alerts`, NOT total_alerts, whenever these differ.
        "sampled_alerts": sampled,
        "alerts_truncated": alerts_truncated,
        "total_clusters": total_clusters,
        "scored_clusters": len(scored_by_id),
        "truncated": truncated or alerts_truncated,
        "degraded": degraded_reason is not None,
        "clusters": out_clusters,
        # Surface KB influence (like explain/investigate do) so a different result
        # after a KB edit isn't mysterious — the ranking was RAG-augmented.
        "rag_chunks_used": rag_used,
    }
    if degraded_reason:
        result["degraded_reason"] = degraded_reason
    if truncated:
        result["skipped_clusters"] = [
            {"cluster_id": c["cluster_id"], "count": c["count"], "reason": "exceeded LLM batch cap"}
            for c in skipped
        ]
    return result


async def _fetch_alerts(
    index: str, query: dict[str, Any] | None, window_minutes: int, max_alerts: int
) -> list[dict[str, Any]]:
    es = get_es()
    # The user-supplied `query` is an arbitrary dict that gets embedded into the
    # ES request body. Run it through the SAME read-only DSL validator that
    # /api/execute uses so triage can't become a bypass for forbidden/expensive
    # constructs (script, scripted_metric, update/delete-by-query, ...).
    if query is not None:
        try:
            validate_dsl(query)
        except Exception as e:
            raise ApiError("dsl_validation_failed", reason=e)
    base_query = query or {"match_all": {}}
    body = {
        "query": {
            "bool": {
                "must": [base_query],
                "filter": [{"range": {"@timestamp": {"gte": f"now-{window_minutes}m"}}}],
            }
        },
        "size": max_alerts,
        "sort": [{"@timestamp": "desc"}],
        # Without this ES caps the reported total at 10000 and we cannot tell a
        # full fetch from a truncated one.
        "track_total_hits": True,
    }
    try:
        resp = await es.search(index=index, body=body)
    except Exception as e:
        raise es_api_error(e)
    hits_body = resp.body.get("hits") or {}
    hits = hits_body.get("hits") or []
    total = hits_body.get("total")
    if isinstance(total, dict):
        total = total.get("value")
    alerts = [{"_id": h.get("_id"), "_source": h.get("_source", {})} for h in hits]
    # `size: max_alerts` sorted @timestamp desc is a SAMPLE of the newest
    # alerts. Reporting len(alerts) as the window's volume meant a daily report
    # over 40,000 alerts rendered "告警 100 · 聚类 12" and described the last few
    # minutes of a 24-hour window as the day's picture, with no truncation mark.
    return alerts, (total if isinstance(total, int) else len(alerts))


def _cluster_to_llm_payload(cluster: dict[str, Any]) -> dict[str, Any]:
    masked = mask_doc(cluster.get("_latest_src") or {})
    sample_json = json.dumps(masked, ensure_ascii=False)[:1500]
    others = sorted(s for s in cluster["_subjects"] if s != cluster["subject_value"])[:3]
    return {
        "cluster_id": cluster["cluster_id"],
        "count": cluster["count"],
        "rule_id": cluster["rule_id"],
        "subject_field": cluster["subject_field"],
        "subject_value": cluster["subject_value"],
        "sample_alert": sample_json,
        "other_subjects": others,
    }
