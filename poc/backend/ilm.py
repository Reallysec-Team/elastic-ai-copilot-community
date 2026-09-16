"""ILM retention bootstrap for the gateway's own audit index.

The audit index (``.rst_copilot_audit``) is the one gateway-owned index that
grows unbounded (one doc per AI call), so it's the one that needs retention.
A simple age-based ILM ``delete`` phase on a *single fixed* index would wipe the
whole index at once — wrong. Retention therefore needs a **rollover** target:
this module makes the audit index a **data stream** with an ILM policy that
rolls over (size/age) and deletes backing indices past the retention window.

SAFE BY DESIGN:
  * Opt-in via ``RST_ILM_BOOTSTRAP=1`` (default OFF — existing deployments are
    untouched).
  * Idempotent: PUTting the policy + template is harmless on re-run.
  * Never reshapes existing data. If the audit name already exists as a concrete
    (non-data-stream) index, it logs migration guidance and does nothing — the
    operator reindexes into the data stream on their own ES.

When enabled on a fresh deployment, ``audit.py`` writes with ``op_type=create``
(required for data streams) and the first write auto-creates the stream under
the template + policy below.
"""

from __future__ import annotations

import logging
import os

from . import audit
from .es_client import get_es

logger = logging.getLogger("rst.ilm")

POLICY_NAME = "rst-copilot-retention"
TEMPLATE_NAME = "rst-copilot-audit-ds"


def enabled() -> bool:
    return os.environ.get("RST_ILM_BOOTSTRAP", "").strip().lower() in ("1", "true", "yes")


def _retention_days() -> int:
    try:
        v = int(os.environ.get("RST_AUDIT_RETENTION_DAYS", "180"))
        return v if v > 0 else 180
    except (TypeError, ValueError):
        return 180


def _rollover_max_age() -> str:
    return os.environ.get("RST_ILM_ROLLOVER_MAX_AGE", "7d").strip() or "7d"


def _policy_body() -> dict:
    return {
        "policy": {
            "phases": {
                "hot": {
                    "actions": {
                        "rollover": {
                            "max_age": _rollover_max_age(),
                            "max_primary_shard_size": "10gb",
                        }
                    }
                },
                "delete": {
                    "min_age": f"{_retention_days()}d",
                    "actions": {"delete": {}},
                },
            }
        }
    }


def _template_body(pattern: str) -> dict:
    return {
        "index_patterns": [pattern],
        "data_stream": {},
        "template": {
            "settings": {
                "index.lifecycle.name": POLICY_NAME,
            }
        },
    }


async def bootstrap() -> None:
    """Create the retention policy + data-stream template (idempotent). No-op
    unless RST_ILM_BOOTSTRAP is set. Never raises."""
    if not enabled():
        return
    es = get_es()
    audit_index = audit.index_name()
    try:
        await es.ilm.put_lifecycle(name=POLICY_NAME, body=_policy_body())
        await es.indices.put_index_template(name=TEMPLATE_NAME, body=_template_body(audit_index))
        logger.info(
            "ilm_bootstrapped",
            extra={"policy": POLICY_NAME, "pattern": audit_index, "retention_days": _retention_days()},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("ilm_bootstrap_failed", extra={"error": str(e)})
        return

    # If the audit name already exists as a concrete index (legacy), we must NOT
    # touch it — a data stream cannot share a name with an index. Surface the
    # migration step instead.
    try:
        exists_index = await es.indices.exists(index=audit_index)
        is_data_stream = False
        try:
            ds = await es.indices.get_data_stream(name=audit_index)
            is_data_stream = bool((ds.body or {}).get("data_streams"))
        except Exception:  # noqa: BLE001
            is_data_stream = False
        if exists_index and not is_data_stream:
            logger.warning(
                "ilm_migration_required — %s already exists as a plain index. The "
                "data-stream template + retention policy are installed, but the "
                "existing index won't be ILM-managed. Reindex it into a data "
                "stream (or delete it on a fresh deploy) to activate retention.",
                audit_index,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("ilm_state_check_failed", extra={"error": str(e)})
