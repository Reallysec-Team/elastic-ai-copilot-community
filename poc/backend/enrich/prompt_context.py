"""Asset-context block for prompt injection + the masking-mode egress gate.

Gate rule (硬题②): inject the operator's real asset context into the LLM prompt
ONLY when the deployment runs an on-prem/trusted LLM — i.e. masking mode ∈
{private, airgapped}. In cloud mode we return None (phase 2 will send non-PII
semantic attributes via a local pseudonym map)."""

from __future__ import annotations

import logging
from typing import Any

from ..es_client import get_es
from ..field_masking import MODE_AIRGAPPED, MODE_PRIVATE, current_mode
from .entity import AssetContext
from .resolver import resolve

logger = logging.getLogger("rst.enrich.prompt_context")


def format_block(ctx: AssetContext) -> str:
    parts = []
    if ctx.get("criticality"):
        parts.append(f"重要度 {ctx['criticality']}")
    if ctx.get("category"):
        parts.append(f"类别 {ctx['category']}")
    if ctx.get("owner"):
        parts.append(f"owner {ctx['owner']}")
    if ctx.get("department"):
        parts.append(f"部门 {ctx['department']}")
    if ctx.get("candidates", 1) > 1:
        parts.append(f"{ctx['candidates']} 个候选")
    detail = "，".join(parts)
    name = ctx.get("business_name") or "(未命名资产)"
    return (
        f"涉及资产:{name}"
        f"（{detail};来源 {ctx.get('source')},置信 {ctx.get('confidence')}）"
    )


async def asset_context_block(raw: dict[str, Any], es=None) -> str | None:
    if current_mode() not in (MODE_PRIVATE, MODE_AIRGAPPED):
        return None  # cloud — no real-value injection (phase 2)
    try:
        ctx = await resolve(raw, es or get_es())
    except Exception as e:  # noqa: BLE001 — best-effort, never break投的 prompt
        logger.debug("asset_context_block resolve failed: %s", e)
        return None
    return format_block(ctx) if ctx else None
