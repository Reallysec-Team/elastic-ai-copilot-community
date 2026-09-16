"""Corrections capture: turn an offhand user correction into a KB entry.

Problem this solves: a customer will say "不对，转账失败要看 event_type=7" once,
in passing, and never open the knowledge-base page to write it down as a
Markdown runbook. If we don't capture it automatically the same wrong query
just gets re-generated next time someone asks a similar question. Two capture
points feed this module (wired by the caller, not here): a thumbs-down
comment on `/api/feedback`, and a correction typed straight into the chat on
`/api/generate`.

Why the reject path exists: `looks_like_correction` and `distill` both exist
to keep noise out of the KB. Most sentences a user types are NOT durable
facts ("再试一次", "结果太多了", "你错了") — they're about *this* query, not
the business domain, and writing them into the KB would pollute every future
prompt that retrieves from it. Only statements that stay true independent of
the current query are worth keeping.

Two injection surfaces, both handled at the prompt layer (see prompts.py):
  1. The correction text itself is unsanitized user input, fenced + guarded
     like every other untrusted-data injection point in this codebase.
  2. `distill`'s OUTPUT is what actually lands in the KB and, from there, gets
     injected into every downstream prompt that retrieves it — so the system
     prompt explicitly forbids the model from emitting anything instructional,
     and we hard-truncate title/content on top of that as a code-side backstop
     in case the model ignores the instruction anyway.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from .llm import parse_json
from .llm_router import get_router
from .prompts import correction_system_prompt
from .rag import get_kb

logger = logging.getLogger("rst.corrections")

DEFAULT_DEDUP_SCORE = 0.92

_TITLE_MAX = 60
_CONTENT_MAX = 500

# Lexical gate: cheap, no LLM call, keeps the 99% of ordinary questions from
# ever reaching `distill`. Deliberately narrow — false positives cost an LLM
# call (cheap-ish); false negatives just mean a correction goes uncaptured
# (the status quo today), so err toward tight rather than loose.
#
# Dropped 注意/记住/其实/不该: measured against 6 hand-written common query
# shapes ("注意力机制相关的日志", "其实我想看昨天的", "记住我这个查询"), these fired
# as false positives with no real correction anywhere near them. A genuine
# correction using this sense of 其实/注意/记住 almost always also carries
# 才是/应该是, which are still in the list.
_ZH_MARKERS = [
    "不对", "错了", "应该是", "才是", "而不是", "我是说", "我的意思是",
    "应该用", "别用",
]

# "不是" alone is too common in ordinary questions ("统计不是 200 的响应码",
# "哪些源 IP 不是内网地址") to treat as a bare substring — those aren't
# corrections, they're negated filter conditions. A real correction's "不是"
# instead opens the sentence or follows a clause break ("是 event_type=7，不是
# status=fail" / "不是，应该看 4740"). NOTE: a plain space does NOT count as a
# separator — Chinese text commonly puts a space before a number/value
# ("不是 200"), and counting it would let exactly the false positives above
# back in.
_BUJIAN_PATTERN = re.compile(r"(?:^|[，,。！？])不是")

_EN_MARKERS = [
    r"\bno,", r"\bactually\b", r"\bshould be\b", r"\bi meant\b",
    r"\bnot\b.+\bbut\b",
]
_EN_PATTERN = re.compile("|".join(_EN_MARKERS), re.IGNORECASE)


def looks_like_correction(text: str) -> bool:
    """Lexical pre-filter — no LLM call. True doesn't mean "capture it", it
    means "worth asking the LLM to look closer"."""
    if not text or not text.strip():
        return False
    if any(marker in text for marker in _ZH_MARKERS):
        return True
    if _BUJIAN_PATTERN.search(text):
        return True
    return bool(_EN_PATTERN.search(text))


def _dedup_score() -> float:
    raw = os.environ.get("RST_CORRECTION_DEDUP_SCORE", "").strip()
    if not raw:
        return DEFAULT_DEDUP_SCORE
    try:
        v = float(raw)
        return v if v >= 0 else DEFAULT_DEDUP_SCORE
    except ValueError:
        logger.warning("invalid_correction_dedup_score", extra={"value": raw})
        return DEFAULT_DEDUP_SCORE


def _truncate(s: Any, limit: int) -> str:
    s = "" if s is None else str(s).strip()
    return s if len(s) <= limit else s[:limit]


async def distill(
    correction: str,
    question: str | None = None,
    index: str | None = None,
    dsl: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """One LLM call: turn a correction into a reusable KB fact, or reject it.

    Returns `{"title": str, "content": str}` or None. Never raises — a bad
    LLM response degrades to "don't capture", the same as no correction at
    all.
    """
    if not correction or not correction.strip():
        return None

    import json as _json

    context_lines = []
    if question:
        context_lines.append(f"用户当时的问题: {question}")
    if index:
        context_lines.append(f"索引: {index}")
    if dsl:
        context_lines.append(f"当时生成的 DSL: {_json.dumps(dsl, ensure_ascii=False)[:600]}")
    context = ("\n".join(context_lines) + "\n\n") if context_lines else ""

    from .prompts import _fence, injection_guard  # local import: private helper reuse

    user_prompt = (
        f"{injection_guard()}"
        f"{context}"
        f"用户纠正原文:\n{_fence(correction, '纠正原文')}\n\n"
        "请按系统提示的 JSON 格式判断这句话是否是可复用的持久事实。"
    )

    raw = ""
    try:
        resp, _provider = await get_router().chat_completion(
            messages=[
                {"role": "system", "content": correction_system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            reasoning="none",  # 判断一句话是不是可复用事实：分类题
        )
        if not resp.choices:
            raise ValueError("model returned no choices")
        raw = resp.choices[0].message.content or ""
        payload = parse_json(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "correction distill failed (%s); raw output (first 500 chars): %s",
            e, raw[:500],
        )
        return None

    if not isinstance(payload, dict) or not payload.get("durable"):
        return None

    title = _truncate(payload.get("title"), _TITLE_MAX)
    content = _truncate(payload.get("content"), _CONTENT_MAX)
    if not title or not content:
        return None
    return {"title": title, "content": content}


async def capture(
    correction: str,
    owner: str,
    question: str | None = None,
    index: str | None = None,
    dsl: dict[str, Any] | None = None,
    gated: bool = True,
) -> str | None:
    """Gate -> distill -> dedup -> write to KB. Returns the new doc_id, or
    None if nothing was captured (not a correction / rejected / duplicate /
    write failure). Best-effort throughout — this sits off the main answer
    path and must never break it.

    `looks_like_correction` exists to save an LLM call on the 99% of ordinary
    questions, not to judge whether the content is worth keeping — that's
    distill's job. Set `gated=False` when the caller's context already proves
    this is a correction (e.g. a comment typed into a thumbs-down "what was
    wrong?" box) — the marker-word text may say nothing that looks like a
    correction on its own ("转账失败对应 event_type=7"), and the lexical gate
    would wrongly drop it. This skips no safety check: distill's own
    reject-unless-durable logic and the length truncation still run either way.
    """
    if gated and not looks_like_correction(correction):
        return None

    distilled = await distill(correction, question=question, index=index, dsl=dsl)
    if distilled is None:
        return None

    kb = get_kb()
    try:
        existing = await kb.retrieve(distilled["content"], top_k=3)
    except Exception as e:  # noqa: BLE001
        logger.warning("correction dedup lookup failed", extra={"error": str(e)[:200]})
        existing = []

    threshold = _dedup_score()
    for chunk in existing:
        meta = chunk.get("metadata") or {}
        score = chunk.get("score") or 0.0
        if meta.get("source") == "correction" and score >= threshold:
            logger.info(
                "correction_dedup_skipped",
                extra={"owner": owner, "score": score, "title": distilled["title"][:60]},
            )
            return None

    metadata: dict[str, Any] = {"source": "correction", "auto": True, "owner": owner}
    if question:
        metadata["question"] = question
    if index:
        metadata["index"] = index

    try:
        result = await kb.add_document(
            title=distilled["title"], content=distilled["content"], metadata=metadata
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("correction kb write failed", extra={"error": str(e)[:200]})
        return None

    doc_id = result.get("doc_id")
    logger.info(
        "correction_captured",
        extra={"doc_id": doc_id, "owner": owner, "title": distilled["title"][:60]},
    )
    return doc_id
