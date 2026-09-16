"""Solutions store — a library of validated (question, index, DSL) examples.

The idea: user asks in natural language → we generate a DSL → executing it
gets real hits → we remember (question, index, DSL) as a proven example. Next
time a similar question comes in for the same index, we hand the model that
example as a few-shot reference instead of guessing from scratch. This lets
the library accumulate automatically at a customer site with no curator.

Failure signals (handled elsewhere, this module just exposes the primitives):
  - the user thumbs-downs a result → `reject`
  - the same owner re-asks a rephrased question shortly after → `recent_questions`
    lets a caller detect that pattern and treat the earlier attempt as unproven.

Cooldown: a freshly recorded solution hasn't yet been "tested" by the absence
of an immediate re-ask, so `find_similar` excludes anything younger than
RST_SOLUTION_COOLDOWN_S (default 300s). This is a query-time filter, not a
background job — simplest thing that works, and it self-corrects as time
passes without needing a sweep/cron.

Two retrieval paths, both required (a customer may not have embedding
configured): kNN over `question_vector` when embeddings are on, `match` BM25
over `question` otherwise. Mirrors the guard/fallback style of `rag.py`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from .embeddings import embed_dim, embedding_configured, get_embedding_client
from .es_client import get_es

logger = logging.getLogger("rst.solutions")

INDEX_NAME = ".rst_copilot_solutions"

DEFAULT_COOLDOWN_S = 300

# kNN score floor. Measured against real bge-m3 vectors: a genuine rephrasing
# scores ~0.93, unrelated questions cluster at ~0.69-0.73 — 0.85 sits cleanly
# in the gap. Distinct from rag.py's 0.75 (that's long-document-chunk
# retrieval; this is short-question-to-short-question, a different score
# distribution).
DEFAULT_MIN_SCORE = 0.85

# BM25 has no comparable absolute scale (it depends on corpus term
# frequencies), so the no-embedding fallback path filters on cheap_similarity
# instead. 0.25 rejects unrelated questions while still passing rephrasings
# that share substrings.
DEFAULT_MIN_SIM = 0.25


def _cooldown_s() -> int:
    raw = os.environ.get("RST_SOLUTION_COOLDOWN_S", "").strip()
    if not raw:
        return DEFAULT_COOLDOWN_S
    try:
        v = int(raw)
        return v if v >= 0 else DEFAULT_COOLDOWN_S
    except ValueError:
        logger.warning("invalid_solution_cooldown", extra={"value": raw})
        return DEFAULT_COOLDOWN_S


def _min_score() -> float:
    raw = os.environ.get("RST_SOLUTION_MIN_SCORE", "").strip()
    if not raw:
        return DEFAULT_MIN_SCORE
    try:
        v = float(raw)
        return v if v >= 0 else DEFAULT_MIN_SCORE
    except ValueError:
        logger.warning("invalid_solution_min_score", extra={"value": raw})
        return DEFAULT_MIN_SCORE


def _min_sim() -> float:
    raw = os.environ.get("RST_SOLUTION_MIN_SIM", "").strip()
    if not raw:
        return DEFAULT_MIN_SIM
    try:
        v = float(raw)
        return v if v >= 0 else DEFAULT_MIN_SIM
    except ValueError:
        logger.warning("invalid_solution_min_sim", extra={"value": raw})
        return DEFAULT_MIN_SIM


def _doc_id(owner: str, index: str, question: str, dsl: dict[str, Any]) -> str:
    """Deterministic id so a repeated (owner, index, question, dsl) overwrites
    the same document instead of piling up duplicates."""
    key = f"{owner}|{index}|{question}|{json.dumps(dsl, sort_keys=True)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


async def _existing_vector_dims(es: Any) -> int | None:
    """Mirrors rag.py's dim-mismatch guard. Best-effort, None if unreadable."""
    try:
        resp = await es.indices.get_mapping(index=INDEX_NAME)
        body = resp.body if hasattr(resp, "body") else resp
        mapping = (body.get(INDEX_NAME) or {}).get("mappings") or {}
        vector = ((mapping.get("properties") or {}).get("question_vector")) or {}
        dims = vector.get("dims")
        return int(dims) if dims is not None else None
    except Exception as e:  # noqa: BLE001
        logger.warning("solutions_index_mapping_read_failed", extra={"error": str(e)[:200]})
        return None


async def ensure_index(dims: int | None = None) -> None:
    """Create the solutions index. Idempotent.

    When embedding isn't configured, the mapping skips `question_vector`
    entirely — a dense_vector field can't be created with dims=0, and there's
    nothing to search with kNN anyway until embedding is turned on.
    """
    es = get_es()
    if dims is None and embedding_configured():
        dims = embed_dim()

    properties: dict[str, Any] = {
        # keyword subfield backs reject_by_question's exact-match filter —
        # a thumbs-down identifies "this question got a wrong answer", and a
        # `match` (BM25 tokenized) filter would also reject unrelated but
        # word-overlapping questions.
        "question": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
        "index": {"type": "keyword"},
        "profile": {"type": "keyword"},
        # DSL shape varies per query — dynamic mapping on it would blow up the
        # index's field count. We only ever fetch it back verbatim, never
        # filter/aggregate on its contents, so disable indexing entirely.
        "dsl": {"type": "object", "enabled": False},
        "hits": {"type": "long"},
        "owner": {"type": "keyword"},
        "created_at": {"type": "date"},
        "rejected": {"type": "boolean"},
        "reject_reason": {"type": "keyword"},
        "use_count": {"type": "long"},
    }
    if dims:
        properties["question_vector"] = {
            "type": "dense_vector",
            "dims": dims,
            "index": True,
            "similarity": "cosine",
        }

    try:
        await es.indices.create(index=INDEX_NAME, body={"mappings": {"properties": properties}})
        logger.info("solutions_index_created", extra={"index": INDEX_NAME, "dims": dims})
        return
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if not ("resource_already_exists_exception" in msg or "already exists" in msg):
            raise

    # Already exists — add the `question.keyword` subfield if an older
    # version of this index predates it. Adding a new (sub-)field to an
    # existing mapping is always a safe, additive change in ES — no reindex
    # needed, existing docs just won't have it populated until re-indexed
    # (irrelevant here since `question` is reindexed on every record_success
    # write anyway, via the deterministic _id overwrite).
    try:
        await es.indices.put_mapping(
            index=INDEX_NAME,
            properties={"question": properties["question"]},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("solutions_index_mapping_update_failed", extra={"error": str(e)[:200]})

    # Already exists — a dims change (embed model swapped) would 400 every
    # future write forever, so fail loudly rather than silently degrading.
    if dims:
        existing_dims = await _existing_vector_dims(es)
        if existing_dims is not None and existing_dims != dims:
            logger.error(
                "solutions_index_dim_mismatch",
                extra={"index": INDEX_NAME, "index_dims": existing_dims, "embed_dims": dims},
            )
            raise RuntimeError(
                f"solutions 索引维度={existing_dims} 与当前 embed 模型维度={dims} 不匹配,"
                f"请删除 {INDEX_NAME} 索引或修正 embedding 配置"
            )


async def record_success(
    question: str,
    index: str,
    dsl: dict[str, Any],
    hits: int,
    owner: str,
    profile: str | None = None,
) -> str | None:
    """Store a validated (question, index, dsl) example. Only hits worth
    remembering: hits <= 0 means the DSL didn't prove itself, so skip it.

    Embedding failure degrades to a vector-less record rather than losing the
    example entirely — BM25 fallback in `find_similar` still finds it.
    """
    if not question or not question.strip() or not dsl:
        return None
    if hits <= 0:
        return None

    doc_id = _doc_id(owner, index, question, dsl)
    doc: dict[str, Any] = {
        "question": question,
        "index": index,
        "profile": profile,
        "dsl": dsl,
        "hits": hits,
        "owner": owner,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rejected": False,
        "reject_reason": None,
        "use_count": 0,
    }

    if embedding_configured():
        try:
            vectors = await get_embedding_client().embed_texts([question])
            if vectors and vectors[0]:
                doc["question_vector"] = vectors[0]
        except Exception as e:  # noqa: BLE001
            logger.warning("solutions_embed_failed", extra={"error": str(e)[:200]})

    await ensure_index(dims=len(doc["question_vector"]) if "question_vector" in doc else None)

    es = get_es()
    await es.index(index=INDEX_NAME, id=doc_id, document=doc, refresh="wait_for")
    logger.info(
        "solution_recorded",
        extra={"doc_id": doc_id, "index": index, "owner": owner, "hits": hits},
    )
    return doc_id


async def reject(question: str, index: str, dsl: dict[str, Any], owner: str, reason: str) -> int:
    """Mark a solution as rejected (thumbs-down). Returns 1 if updated, 0 if
    the document doesn't exist — never raises for a missing doc."""
    doc_id = _doc_id(owner, index, question, dsl)
    es = get_es()
    try:
        await es.update(
            index=INDEX_NAME,
            id=doc_id,
            doc={"rejected": True, "reject_reason": reason},
            refresh="wait_for",
        )
    except Exception as e:  # noqa: BLE001
        if "document_missing_exception" in str(e) or "not_found" in str(e).lower():
            return 0
        if "index_not_found_exception" in str(e):
            return 0
        raise
    logger.info("solution_rejected", extra={"doc_id": doc_id, "reason": reason[:200]})
    return 1


async def reject_by_question(question: str, index: str, owner: str, reason: str) -> int:
    """Reject every stored solution for (owner, index, question), regardless
    of which DSL it was recorded with.

    `reject`'s id is derived from the DSL bytes, but the DSL the frontend
    sends with a thumbs-down (the generation-time DSL) isn't necessarily the
    one `record_success` stored (the execution-time DSL, post `buildExecDsl`
    injection of size/sort/track_total_hits) — so the id-based lookup can
    silently miss. A thumbs-down means "this question's answer was wrong",
    and the question is what identifies that, not the DSL bytes.

    Uses `question.keyword` (exact match) rather than `match` (tokenized) —
    "登录失败的事件" must not also reject "登录失败的账号".
    """
    if not question or not question.strip():
        return 0
    es = get_es()
    try:
        resp = await es.update_by_query(
            index=INDEX_NAME,
            query={
                "bool": {
                    "filter": [
                        _owner_term(owner),
                        {"term": {"index": index}},
                        {"term": {"question.keyword": question}},
                    ]
                }
            },
            script={
                "source": "ctx._source.rejected = true; ctx._source.reject_reason = params.reason",
                "params": {"reason": reason},
            },
            refresh=True,
        )
    except Exception as e:  # noqa: BLE001
        if "index_not_found_exception" in str(e):
            return 0
        logger.warning("solutions_reject_by_question_failed", extra={"error": str(e)[:300]})
        return 0
    body = resp.body if hasattr(resp, "body") else resp
    updated = int(body.get("updated") or 0)
    logger.info(
        "solution_rejected_by_question",
        extra={"index": index, "owner": owner, "reason": reason[:200], "updated": updated},
    )
    return updated


def _owner_term(owner: str) -> dict[str, Any]:
    """`{"term": {"owner": owner}}`，顺带挡住「传了个 dict 进来」。

    这条库的所有 owner 过滤都是 ES 的 term 查询，而这一层上面全是 best-effort：
    传错类型时 ES 回 400、异常被吞、召回恒空，功能整条静默失效，没有任何东西会红。
    `/api/generate` 就这么把 `current_user()` 的 dict 当主人传了下来。类型错在这里
    炸出来，比在生产日志里当 warning 躺着强。
    """
    if not isinstance(owner, str):
        raise TypeError(f"owner must be a str, got {type(owner).__name__}: {owner!r}")
    return {"term": {"owner": owner}}


async def find_similar(
    question: str,
    index: str,
    profile: str | None = None,
    top_k: int = 3,
    owner: str | None = None,
) -> list[dict[str, Any]]:
    """Find validated examples similar to `question` for the same index.

    Best-effort: any ES / embedding error returns []. This sits on the main
    query path, so a solutions-store hiccup must never break a query.

    `owner` 给了就只召回这个人自己的例子。这条库是喂进 NL→DSL few-shot 的
    「已验证示例」，跨人共享意味着任何能写进去的账号都在影响别人（含管理员）
    的生成结果。写入侧已经限成 analyst/admin（见 main.py 的 record_success
    调用），检索侧再按主人隔离一层：两处都失守才谈得上投毒。
    """
    if not question or not question.strip():
        return []

    cutoff = datetime.now(timezone.utc).timestamp() - _cooldown_s()
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()

    filters: list[dict[str, Any]] = [
        {"term": {"rejected": False}},
        {"range": {"created_at": {"lte": cutoff_iso}}},
    ]
    if owner:
        filters.append(_owner_term(owner))
    if profile:
        # Same index always qualifies; same profile is an additional (not
        # exclusive) way in — a shared profile can surface a good example
        # from a differently-named but structurally similar index.
        filters.append({"bool": {"should": [{"term": {"index": index}}, {"term": {"profile": profile}}]}})
    else:
        filters.append({"term": {"index": index}})

    es = get_es()

    if embedding_configured():
        try:
            vectors = await get_embedding_client().embed_texts([question])
        except Exception as e:  # noqa: BLE001
            logger.warning("solutions_find_embed_failed", extra={"error": str(e)[:200]})
            return []
        if not vectors or not vectors[0]:
            return []
        knn = {
            "field": "question_vector",
            "query_vector": vectors[0],
            "k": top_k,
            "num_candidates": max(top_k * 10, 50),
            "filter": {"bool": {"filter": filters}},
        }
        search_kwargs: dict[str, Any] = {"knn": knn, "size": top_k}
    else:
        query = {"bool": {"must": {"match": {"question": question}}, "filter": filters}}
        search_kwargs = {"query": query, "size": top_k}

    try:
        resp = await es.search(
            index=INDEX_NAME,
            _source=["question", "dsl", "index", "profile", "hits", "created_at"],
            **search_kwargs,
        )
    except Exception as e:  # noqa: BLE001
        if "index_not_found_exception" in str(e):
            return []
        logger.warning("solutions_find_similar_failed", extra={"error": str(e)[:300]})
        return []

    body = resp.body if hasattr(resp, "body") else resp
    hits = (body.get("hits") or {}).get("hits") or []
    out: list[dict[str, Any]] = []
    for h in hits:
        src = h.get("_source") or {}
        out.append({
            "question": src.get("question"),
            "dsl": src.get("dsl"),
            "index": src.get("index"),
            "profile": src.get("profile"),
            "hits": src.get("hits"),
            "score": h.get("_score"),
            "created_at": src.get("created_at"),
        })

    # Relevance floor — an irrelevant example fed into the prompt as a
    # "verified" reference actively misleads the model, worse than no example
    # at all. kNN cosine scores are comparable in absolute terms, so filter
    # on the score directly. BM25 scores aren't (they depend on corpus term
    # stats), so fall back to cheap_similarity against the matched question
    # instead. Deliberately NOT applying cheap_similarity on top of the kNN
    # path too: a true rephrasing ("登录失败" vs "认证不通过") can share almost
    # no character n-grams while the embedding correctly recognizes it — an
    # extra n-gram filter there would throw away good kNN recalls.
    if embedding_configured():
        out = [r for r in out if (r.get("score") or 0.0) >= _min_score()]
    else:
        min_sim = _min_sim()
        out = [r for r in out if cheap_similarity(question, r.get("question") or "") >= min_sim]

    out.sort(key=lambda r: r.get("score") or 0.0, reverse=True)
    return out


async def recent_questions(owner: str, within_s: int = 300, limit: int = 10) -> list[dict[str, Any]]:
    """Recent questions (rejected included) by `owner` in the last `within_s`
    seconds — used to detect a user rephrasing the same ask over and over."""
    since = datetime.now(timezone.utc).timestamp() - within_s
    since_iso = datetime.fromtimestamp(since, tz=timezone.utc).isoformat()

    es = get_es()
    try:
        resp = await es.search(
            index=INDEX_NAME,
            query={
                "bool": {
                    "filter": [
                        _owner_term(owner),
                        {"range": {"created_at": {"gte": since_iso}}},
                    ]
                }
            },
            sort=[{"created_at": {"order": "desc"}}],
            size=limit,
            _source=["question", "index", "created_at", "rejected"],
        )
    except Exception as e:  # noqa: BLE001
        if "index_not_found_exception" in str(e):
            return []
        logger.warning("solutions_recent_questions_failed", extra={"error": str(e)[:300]})
        return []

    body = resp.body if hasattr(resp, "body") else resp
    hits = (body.get("hits") or {}).get("hits") or []
    return [
        {
            "question": (h.get("_source") or {}).get("question"),
            "index": (h.get("_source") or {}).get("index"),
            "created_at": (h.get("_source") or {}).get("created_at"),
            "rejected": (h.get("_source") or {}).get("rejected"),
        }
        for h in hits
    ]


def _char_ngrams(s: str, n: int = 2) -> set[str]:
    s = (s or "").strip()
    if len(s) < n:
        return {s} if s else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def cheap_similarity(a: str, b: str) -> float:
    """Embedding-free fallback similarity, 0..1. Character n-gram Dice
    coefficient — works reasonably on CJK text where there's no whitespace
    tokenization to lean on, and catches rephrasings that share substrings
    even when word order/particles differ (e.g. 登录失败的事件 vs
    哪些账号登录失败了)."""
    grams_a = _char_ngrams(a)
    grams_b = _char_ngrams(b)
    if not grams_a or not grams_b:
        return 0.0
    overlap = len(grams_a & grams_b)
    return (2.0 * overlap) / (len(grams_a) + len(grams_b))
