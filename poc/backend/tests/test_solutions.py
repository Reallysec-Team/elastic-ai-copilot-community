"""Solutions store: recording, rejection, cooldown-gated retrieval.

No real ES / embedding calls — `get_es` and the embedding functions are
monkeypatched, mirroring test_rag_embed_gate.py's style.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import solutions  # noqa: E402


class _FakeES:
    """Records the last call made to each method so tests can assert on the
    request shape sent to ES."""

    def __init__(self):
        self.indexed: dict = {}
        self.updated: list = []
        self.last_search_kwargs: dict | None = None
        self.search_hits: list = []
        self.search_raises: Exception | None = None
        self.index_error: Exception | None = None
        self.update_error: Exception | None = None
        self.ubq_raises: Exception | None = None

        class _Indices:
            async def create(_self, index=None, body=None):
                return {}

            async def get_mapping(_self, index=None):
                return {index: {"mappings": {"properties": {}}}}

            async def put_mapping(_self, index=None, properties=None):
                return {}

        self.indices = _Indices()

    async def index(self, *, index, id, document, refresh=None):
        if self.index_error:
            raise self.index_error
        self.indexed[id] = document
        return {"_id": id}

    async def update(self, *, index, id, doc, refresh=None):
        if self.update_error:
            raise self.update_error
        self.updated.append((id, doc))
        if id not in self.indexed:
            raise RuntimeError("document_missing_exception")
        self.indexed[id].update(doc)

    async def search(self, *, index, **kwargs):
        self.last_search_kwargs = kwargs
        if self.search_raises:
            raise self.search_raises
        return {"hits": {"hits": self.search_hits}}

    async def update_by_query(self, *, index, query, script, refresh=None):
        if self.ubq_raises:
            raise self.ubq_raises
        terms = {k: v for f in query["bool"]["filter"] for k, v in f["term"].items()}
        updated = 0
        for doc in self.indexed.values():
            if (
                doc.get("owner") == terms.get("owner")
                and doc.get("index") == terms.get("index")
                and doc.get("question") == terms.get("question.keyword")
            ):
                doc["rejected"] = True
                doc["reject_reason"] = script["params"]["reason"]
                updated += 1
        return {"updated": updated}


@pytest.fixture(autouse=True)
def _es(monkeypatch):
    fake = _FakeES()
    monkeypatch.setattr(solutions, "get_es", lambda: fake)
    return fake


@pytest.fixture
def embedding_off(monkeypatch):
    monkeypatch.setattr(solutions, "embedding_configured", lambda: False)


@pytest.fixture
def embedding_on(monkeypatch):
    monkeypatch.setattr(solutions, "embedding_configured", lambda: True)
    monkeypatch.setattr(solutions, "embed_dim", lambda: 4)

    class _Embedder:
        async def embed_texts(self, texts):
            return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    monkeypatch.setattr(solutions, "get_embedding_client", lambda: _Embedder())


# ─────────────────────────── record_success ───────────────────────────


@pytest.mark.asyncio
async def test_record_success_skips_zero_hits(_es, embedding_off):
    doc_id = await solutions.record_success("q", "idx", {"query": {}}, hits=0, owner="u1")
    assert doc_id is None
    assert _es.indexed == {}


@pytest.mark.asyncio
async def test_record_success_skips_empty_question_or_dsl(_es, embedding_off):
    assert await solutions.record_success("", "idx", {"query": {}}, hits=5, owner="u1") is None
    assert await solutions.record_success("q", "idx", {}, hits=5, owner="u1") is None


@pytest.mark.asyncio
async def test_record_success_deterministic_id(_es, embedding_off):
    dsl = {"query": {"match_all": {}}}
    id1 = await solutions.record_success("q", "idx", dsl, hits=3, owner="u1")
    id2 = await solutions.record_success("q", "idx", dsl, hits=3, owner="u1")
    assert id1 == id2
    assert len(_es.indexed) == 1


@pytest.mark.asyncio
async def test_record_success_writes_expected_fields(_es, embedding_off):
    doc_id = await solutions.record_success(
        "q", "idx", {"query": {}}, hits=7, owner="u1", profile="p1"
    )
    doc = _es.indexed[doc_id]
    assert doc["rejected"] is False
    assert doc["use_count"] == 0
    assert doc["hits"] == 7
    assert doc["profile"] == "p1"
    assert "question_vector" not in doc


@pytest.mark.asyncio
async def test_record_success_embeds_when_configured(_es, embedding_on):
    doc_id = await solutions.record_success("q", "idx", {"query": {}}, hits=1, owner="u1")
    assert _es.indexed[doc_id]["question_vector"] == [0.1, 0.2, 0.3, 0.4]


@pytest.mark.asyncio
async def test_record_success_survives_embed_failure(_es, monkeypatch):
    monkeypatch.setattr(solutions, "embedding_configured", lambda: True)
    monkeypatch.setattr(solutions, "embed_dim", lambda: 4)

    class _BrokenEmbedder:
        async def embed_texts(self, texts):
            raise RuntimeError("provider down")

    monkeypatch.setattr(solutions, "get_embedding_client", lambda: _BrokenEmbedder())

    doc_id = await solutions.record_success("q", "idx", {"query": {}}, hits=1, owner="u1")
    assert doc_id is not None
    assert "question_vector" not in _es.indexed[doc_id]


# ─────────────────────────── reject ───────────────────────────


@pytest.mark.asyncio
async def test_reject_marks_existing_doc(_es, embedding_off):
    doc_id = await solutions.record_success("q", "idx", {"query": {}}, hits=1, owner="u1")
    n = await solutions.reject("q", "idx", {"query": {}}, owner="u1", reason="wrong")
    assert n == 1
    assert _es.indexed[doc_id]["rejected"] is True
    assert _es.indexed[doc_id]["reject_reason"] == "wrong"


@pytest.mark.asyncio
async def test_reject_missing_doc_returns_zero(_es, embedding_off):
    n = await solutions.reject("never stored", "idx", {"query": {}}, owner="u1", reason="x")
    assert n == 0


# ─────────────────────────── reject_by_question ───────────────────────────


@pytest.mark.asyncio
async def test_reject_by_question_matches_regardless_of_dsl(_es, embedding_off):
    # record_success's DSL differs from what a thumbs-down carries (gen-time
    # vs exec-time DSL) — reject_by_question must not care about that.
    await solutions.record_success("登录失败的事件", "idx", {"query": {"exec": 1}}, hits=3, owner="u1")
    n = await solutions.reject_by_question("登录失败的事件", "idx", owner="u1", reason="wrong")
    assert n == 1
    doc = next(iter(_es.indexed.values()))
    assert doc["rejected"] is True
    assert doc["reject_reason"] == "wrong"


@pytest.mark.asyncio
async def test_reject_by_question_does_not_hit_similar_questions(_es, embedding_off):
    await solutions.record_success("登录失败的事件", "idx", {"query": {}}, hits=3, owner="u1")
    await solutions.record_success("登录失败的账号", "idx", {"query": {}}, hits=2, owner="u1")
    n = await solutions.reject_by_question("登录失败的事件", "idx", owner="u1", reason="wrong")
    assert n == 1
    rejected = [d for d in _es.indexed.values() if d["rejected"]]
    assert len(rejected) == 1
    assert rejected[0]["question"] == "登录失败的事件"


@pytest.mark.asyncio
async def test_reject_by_question_missing_index_returns_zero(_es, embedding_off):
    _es.ubq_raises = RuntimeError("index_not_found_exception")
    n = await solutions.reject_by_question("q", "idx", owner="u1", reason="x")
    assert n == 0


@pytest.mark.asyncio
async def test_reject_by_question_es_error_returns_zero_not_raise(_es, embedding_off):
    _es.ubq_raises = RuntimeError("cluster on fire")
    n = await solutions.reject_by_question("q", "idx", owner="u1", reason="x")
    assert n == 0


# ─────────────────────────── find_similar ───────────────────────────


@pytest.mark.asyncio
async def test_find_similar_uses_match_when_embedding_off(_es, embedding_off):
    _es.search_hits = []
    await solutions.find_similar("some question", "idx")
    assert "knn" not in _es.last_search_kwargs
    assert "match" in str(_es.last_search_kwargs["query"])


@pytest.mark.asyncio
async def test_find_similar_uses_knn_when_embedding_on(_es, embedding_on):
    _es.search_hits = []
    await solutions.find_similar("some question", "idx")
    assert "knn" in _es.last_search_kwargs
    assert _es.last_search_kwargs["knn"]["field"] == "question_vector"


@pytest.mark.asyncio
async def test_find_similar_filters_rejected_and_cooldown(_es, embedding_off):
    await solutions.find_similar("q", "idx")
    kwargs = _es.last_search_kwargs
    filters = kwargs["query"]["bool"]["filter"]
    assert {"term": {"rejected": False}} in filters
    assert any("created_at" in f.get("range", {}) for f in filters)
    range_filter = next(f["range"]["created_at"] for f in filters if "range" in f)
    assert "lte" in range_filter


@pytest.mark.asyncio
async def test_find_similar_returns_results_sorted_by_score(_es, embedding_on):
    _es.search_hits = [
        {"_score": 0.9, "_source": {"question": "a", "dsl": {}, "index": "idx", "hits": 1}},
        {"_score": 0.95, "_source": {"question": "b", "dsl": {}, "index": "idx", "hits": 2}},
    ]
    out = await solutions.find_similar("q", "idx")
    assert [r["question"] for r in out] == ["b", "a"]


# ─────────────────────────── find_similar relevance floor ───────────────────────────


@pytest.mark.asyncio
async def test_find_similar_knn_drops_results_below_min_score(_es, embedding_on):
    _es.search_hits = [
        {"_score": 0.93, "_source": {"question": "登录失败的事件改述", "dsl": {}, "index": "idx", "hits": 1}},
        {"_score": 0.73, "_source": {"question": "磁盘空间不足", "dsl": {}, "index": "idx", "hits": 1}},
        {"_score": 0.69, "_source": {"question": "今天天气怎么样", "dsl": {}, "index": "idx", "hits": 1}},
    ]
    out = await solutions.find_similar("q", "idx")
    assert [r["question"] for r in out] == ["登录失败的事件改述"]


@pytest.mark.asyncio
async def test_find_similar_knn_min_score_configurable(_es, embedding_on, monkeypatch):
    monkeypatch.setenv("RST_SOLUTION_MIN_SCORE", "0.7")
    _es.search_hits = [
        {"_score": 0.73, "_source": {"question": "磁盘空间不足", "dsl": {}, "index": "idx", "hits": 1}},
    ]
    out = await solutions.find_similar("q", "idx")
    assert len(out) == 1


@pytest.mark.asyncio
async def test_find_similar_bm25_drops_dissimilar_questions(_es, embedding_off):
    _es.search_hits = [
        {"_score": 3.0, "_source": {"question": "登录失败的事件", "dsl": {}, "index": "idx", "hits": 1}},
        {"_score": 2.0, "_source": {"question": "磁盘空间不足的告警", "dsl": {}, "index": "idx", "hits": 1}},
    ]
    out = await solutions.find_similar("哪些账号登录失败了", "idx")
    assert [r["question"] for r in out] == ["登录失败的事件"]


@pytest.mark.asyncio
async def test_find_similar_bm25_min_sim_configurable(_es, embedding_off, monkeypatch):
    monkeypatch.setenv("RST_SOLUTION_MIN_SIM", "0.9")
    _es.search_hits = [
        {"_score": 3.0, "_source": {"question": "登录失败的事件", "dsl": {}, "index": "idx", "hits": 1}},
    ]
    out = await solutions.find_similar("哪些账号登录失败了", "idx")
    assert out == []


@pytest.mark.asyncio
async def test_find_similar_returns_empty_on_es_error(_es, embedding_off):
    _es.search_raises = RuntimeError("cluster on fire")
    out = await solutions.find_similar("q", "idx")
    assert out == []


@pytest.mark.asyncio
async def test_find_similar_returns_empty_when_index_missing(_es, embedding_off):
    _es.search_raises = RuntimeError("index_not_found_exception")
    out = await solutions.find_similar("q", "idx")
    assert out == []


@pytest.mark.asyncio
async def test_find_similar_returns_empty_on_embed_error(_es, monkeypatch):
    monkeypatch.setattr(solutions, "embedding_configured", lambda: True)

    class _BrokenEmbedder:
        async def embed_texts(self, texts):
            raise RuntimeError("provider down")

    monkeypatch.setattr(solutions, "get_embedding_client", lambda: _BrokenEmbedder())
    out = await solutions.find_similar("q", "idx")
    assert out == []


# ─────────────────────────── recent_questions ───────────────────────────


@pytest.mark.asyncio
async def test_recent_questions_returns_empty_on_missing_index(_es):
    _es.search_raises = RuntimeError("index_not_found_exception")
    out = await solutions.recent_questions("u1")
    assert out == []


@pytest.mark.asyncio
async def test_recent_questions_maps_hits(_es):
    _es.search_hits = [
        {"_source": {"question": "q1", "index": "idx", "created_at": "t1", "rejected": False}},
    ]
    out = await solutions.recent_questions("u1", within_s=60)
    assert out == [{"question": "q1", "index": "idx", "created_at": "t1", "rejected": False}]


# ─────────────────────────── cheap_similarity ───────────────────────────


def test_cheap_similarity_identical_is_one():
    assert solutions.cheap_similarity("登录失败的事件", "登录失败的事件") == 1.0


def test_cheap_similarity_empty_is_zero():
    assert solutions.cheap_similarity("", "登录失败") == 0.0


def test_cheap_similarity_rephrasing_scores_moderate_to_high():
    score = solutions.cheap_similarity("登录失败的事件", "哪些账号登录失败了")
    assert 0.3 < score < 0.9


def test_cheap_similarity_unrelated_scores_low():
    score = solutions.cheap_similarity("登录失败的事件", "磁盘空间不足")
    assert score < 0.15


def test_cheap_similarity_rephrasing_beats_unrelated():
    related = solutions.cheap_similarity("登录失败的事件", "哪些账号登录失败了")
    unrelated = solutions.cheap_similarity("登录失败的事件", "磁盘空间不足")
    assert related > unrelated


def test_owner_term_refuses_a_non_string_owner():
    """owner 传错类型要当场炸，不能变成一条 ES 400 + 一行 warning。

    这一层的调用方全是 best-effort：`find_similar` 的异常被吞成「没有示例」，
    于是「整个加速器不工作」和「这次确实没有匹配的例子」长得一模一样。
    """
    assert solutions._owner_term("alice") == {"term": {"owner": "alice"}}
    with pytest.raises(TypeError):
        solutions._owner_term({"username": "alice", "roles": ["admin"]})
