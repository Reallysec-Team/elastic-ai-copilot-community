"""RAG knowledge-base endpoints.

This module exports a FastAPI `APIRouter`, mounted in `main.py` via
`app.include_router(rag_router)`.

Routes:
  POST   /api/kb/upload          — chunk + embed + index a document
  GET    /api/kb/documents       — list indexed documents
  POST   /api/kb/search          — kNN retrieve top-k chunks for a query
  DELETE /api/kb/{doc_id}        — delete all chunks for a document

Auth / license gating: `/api/kb/` is NOT in `license_gate._ALWAYS_ALLOW_PREFIXES`
— RAG calls the LLM, so it is blocked when the license is in a hard-fail state
(expired / revoked / invalid). It does not consume the unactivated trial quota.
The shared-secret middleware covers it via the `/api/*` prefix.

A missing embedding-model config (`RST_EMBED_MODEL`, or no enabled LLM
provider) surfaces as HTTP 503 — it is an operator config gap, not a server
fault, so it must not land in the 5xx-crash bucket as a 500.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from . import llm_cost
from .auth import require_admin
from .rag import KBDimsMismatch, get_kb
from .api_errors import ApiError

logger = logging.getLogger("rst.rag.api")

router = APIRouter(tags=["rag"])
llm_post = llm_cost.marker(router)  # 见 llm_cost.py


# ─────────────────────────── Models ───────────────────────────


class KBUploadRequest(BaseModel):
    title: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class KBUploadResponse(BaseModel):
    doc_id: str
    chunk_count: int
    total_chars: int


class KBSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    doc_ids: list[str] | None = None


class KBSearchHit(BaseModel):
    doc_id: str | None
    chunk_id: str | None
    title: str | None
    content: str | None
    score: float | None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KBDocument(BaseModel):
    doc_id: str | None
    title: str | None
    chunk_count: int
    first_indexed_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KBDeleteResponse(BaseModel):
    deleted: int


# ─────────────────────────── Routes ───────────────────────────


@router.post("/api/kb/upload", response_model=KBUploadResponse)
async def kb_upload(req: KBUploadRequest, request: Request) -> KBUploadResponse:
    # Admin-gated: knowledge-base text is injected into the triage /
    # investigate prompts and the system prompt tells the model to give it
    # priority, so an uploader can steer verdicts across the whole product.
    # That is a configuration-level power, not an analyst one.
    require_admin(request)
    if not req.content or not req.content.strip():
        raise ApiError("content_empty")
    if not req.title or not req.title.strip():
        raise ApiError("title_empty")

    kb = get_kb()
    try:
        # No pre-create here: add_document creates the index at the embedding
        # model's actual output dimension (avoids the embed-dim footgun).
        result = await kb.add_document(
            title=req.title.strip(),
            content=req.content,
            metadata=req.metadata or {},
        )
    except ValueError as e:
        raise ApiError("invalid_request", reason=e)
    except RuntimeError as e:
        # Missing embedding config (RST_EMBED_MODEL unset / no enabled LLM
        # provider) — an operator config gap, not a server fault. 503 keeps it
        # semantically distinct from a 500 crash and carries the clear message.
        raise ApiError("embedding_not_configured", 503, reason=e)
    except Exception:  # noqa: BLE001
        logger.exception("kb_upload_failed", extra={"title": req.title[:120]})
        # 固定文案：ES 异常字符串里带索引名和节点地址，回给客户端等于泄露拓扑。
        # 细节留给上面那行 logger.exception。
        raise ApiError("kb_upload_failed", 500)

    logger.info(
        "kb_upload",
        extra={
            "doc_id": result["doc_id"],
            "chunk_count": result["chunk_count"],
            "total_chars": result["total_chars"],
        },
    )
    return KBUploadResponse(**result)


@router.get("/api/kb/documents", response_model=list[KBDocument])
async def kb_documents() -> list[KBDocument]:
    kb = get_kb()
    try:
        await kb.ensure_index()
        rows = await kb.list_documents()
    except KBDimsMismatch as e:
        # 我们自己诊断出来的、可以直接告诉管理员的原因(换了 embedding 模型),
        # 不该躲在「请查看服务端日志」后面。
        raise ApiError("kb_dims_mismatch", 500, index_dims=e.index_dims, embed_dims=e.embed_dims)
    except Exception:  # noqa: BLE001
        logger.exception("kb_list_failed")
        # 固定文案：ES 异常字符串里带索引名和节点地址，回给客户端等于泄露拓扑。
        # 细节留给上面那行 logger.exception。
        raise ApiError("kb_list_failed", 500)
    return [KBDocument(**r) for r in rows]


@llm_post("/api/kb/search", rpm_env="RST_RATELIMIT_KB_SEARCH", rpm=60.0,
          response_model=list[KBSearchHit])
async def kb_search(req: KBSearchRequest) -> list[KBSearchHit]:
    if not req.query or not req.query.strip():
        raise ApiError("query_empty")
    if req.top_k <= 0 or req.top_k > 50:
        raise ApiError("top_k_out_of_range")

    kb = get_kb()
    try:
        await kb.ensure_index()
        hits = await kb.retrieve(
            query=req.query,
            top_k=req.top_k,
            filter_doc_ids=req.doc_ids,
        )
    except ValueError as e:
        raise ApiError("invalid_request", reason=e)
    except RuntimeError as e:
        # Missing embedding config — operator config gap, not a server fault.
        raise ApiError("embedding_not_configured", 503, reason=e)
    except Exception:  # noqa: BLE001
        logger.exception("kb_search_failed", extra={"query_len": len(req.query)})
        # 固定文案：ES 异常字符串里带索引名和节点地址，回给客户端等于泄露拓扑。
        # 细节留给上面那行 logger.exception。
        raise ApiError("kb_search_failed", 500)

    logger.info(
        "kb_search",
        extra={"query_len": len(req.query), "top_k": req.top_k, "hits": len(hits)},
    )
    return [KBSearchHit(**h) for h in hits]


@router.delete("/api/kb/{doc_id}", response_model=KBDeleteResponse)
async def kb_delete(doc_id: str, request: Request) -> KBDeleteResponse:
    require_admin(request)
    if not doc_id or not doc_id.strip():
        raise ApiError("doc_id_required")
    kb = get_kb()
    try:
        await kb.ensure_index()
        deleted = await kb.delete_document(doc_id.strip())
    except ValueError as e:
        raise ApiError("invalid_request", reason=e)
    except Exception:  # noqa: BLE001
        logger.exception("kb_delete_failed", extra={"doc_id": doc_id})
        # 固定文案：ES 异常字符串里带索引名和节点地址，回给客户端等于泄露拓扑。
        # 细节留给上面那行 logger.exception。
        raise ApiError("kb_delete_failed", 500)
    return KBDeleteResponse(deleted=deleted)
