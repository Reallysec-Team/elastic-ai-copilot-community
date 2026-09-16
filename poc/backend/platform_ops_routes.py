"""Platform check-up API — is the customer's ELK itself healthy?

  GET /api/platform/checkup   run every check, return 检查项 → 结论 → 建议

Read-only, and deliberately so: every finding hands back a paste-able command
instead of applying it. Asking a customer to grant this gateway `manage_ilm`
or Fleet-write so it can "fix things itself" turns a read-only product into
one that can break their cluster, which is not a trade a security team should
be asked to make.

Deterministic rules, no LLM. Most ELK troubleshooting is a checklist, not
reasoning — a disk watermark flipping indices to read-only either happened or
it didn't. That keeps the page cheap enough to run on every visit, and its
answers reproducible. Explaining the findings in plain language is where a
model earns its place, and that is the next slice, not this one.

Note what this does NOT inherit: `validate_dsl`, the index whitelist and
`mask_doc` all live on the `_search` path, so none of them cover a call to
`_cluster/health`. The guardrail here is that `platform_ops.probe` exposes
named read-only functions and no generic request builder — there is no path
for a caller to reach a write API through it.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Request

from . import audit, license_state as ls, llm_cost
from .auth import current_user
from .platform_ops import checks, interpret as interpret_mod
from .api_errors import ApiError

logger = logging.getLogger("rst.platform_ops.api")

router = APIRouter(tags=["platform-ops"])
llm_post = llm_cost.marker(router)  # 见 llm_cost.py

FEATURE = "platform_ops_copilot"


@router.get("/api/platform/checkup")
async def platform_checkup(request: Request) -> dict[str, Any]:
    if not ls.feature_allowed(FEATURE):
        raise ApiError("platform_checkup_needs_standard", 403)
    user = current_user(request)
    start = time.perf_counter()
    try:
        report = await checks.run_all()
    except Exception as e:  # noqa: BLE001 — a check-up that 500s is useless
        logger.exception("platform_checkup_failed")
        raise ApiError("platform_checkup_failed", 500, reason=e)

    duration_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "platform_checkup",
        extra={
            "verdict": report.get("verdict"),
            "counts": report.get("counts"),
            "duration_ms": duration_ms,
            "user": user,
        },
    )
    # These calls reach past every guardrail the search path has, so they get
    # their own audit trail — nothing else in the product would record that
    # this gateway read the customer's cluster topology.
    audit.fire_and_forget(audit.write_event(
        "platform_checkup",
        index=None,
        user=user,
        license_status=ls.get_state()["status"],
        duration_ms=duration_ms,
        extra={
            "verdict": report.get("verdict"),
            "counts": report.get("counts"),
            "checks": [c.get("id") for c in report.get("checks", [])],
        },
    ))
    return report


@llm_post("/api/platform/interpret",
          rpm_env="RST_RATELIMIT_PLATFORM_INTERPRET", rpm=30.0)
async def platform_interpret(request: Request) -> dict[str, Any]:
    """Check-up plus a plain-language reading of it.

    Separate from /checkup on purpose. The check-up is rules-only and must stay
    instant enough to run on every page load; folding an LLM call into it would
    cost that. What a model adds here is what rules cannot: tying findings
    together into one story (a full disk flips indices read-only, writes fail,
    a data stream goes quiet — three findings, one cause), reading the
    customer's own knowledge base for what a given stream is supposed to do,
    and saying which thing to fix first.

    It re-runs the checks rather than accepting a report from the client: the
    report would otherwise be caller-controlled text going straight into a
    prompt, and the checks are cheap ES reads. The caller gets both back, so
    the reading it sees always matches the findings it sees.
    """
    if not ls.feature_allowed(FEATURE):
        raise ApiError("platform_checkup_needs_standard", 403)
    user = current_user(request)
    start = time.perf_counter()

    # The license gate charged an unactivated-trial unit before this handler
    # ran; a healthy cluster short-circuits without calling the LLM, so give it
    # back rather than bill a demo user for a call we never made.
    is_unactivated = ls.get_state().get("status") == ls.STATUS_UNACTIVATED

    try:
        report = await checks.run_all()
    except Exception as e:  # noqa: BLE001
        if is_unactivated:
            await ls.refund_unactivated_quota()
        logger.exception("platform_interpret_checks_failed")
        raise ApiError("platform_checkup_failed", 500, reason=e)

    reading = await interpret_mod.interpret(report)
    if is_unactivated and report.get("verdict") == "ok":
        await ls.refund_unactivated_quota()

    duration_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "platform_interpret",
        extra={
            "verdict": report.get("verdict"),
            "degraded": reading.get("degraded"),
            "rag_chunks_used": reading.get("rag_chunks_used"),
            "actions": len(reading.get("actions") or []),
            "duration_ms": duration_ms,
            "user": user,
        },
    )
    audit.fire_and_forget(audit.write_event(
        "platform_interpret",
        index=None,
        user=user,
        license_status=ls.get_state()["status"],
        duration_ms=duration_ms,
        extra={
            "verdict": report.get("verdict"),
            "degraded": reading.get("degraded"),
            "rag_chunks_used": reading.get("rag_chunks_used"),
        },
    ))
    return {"report": report, "interpretation": reading}
