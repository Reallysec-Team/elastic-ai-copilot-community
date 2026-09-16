"""Indices the PRODUCT owns, as opposed to the customer's data.

The index picker offers everything the gateway can see. Most of the product's
own storage is dot-prefixed and already hidden by the system-index filter, but
the baseline pack's indices are not — so `baseline-rules` (a compliance-rule
catalogue with fields like `judge` and `remediation_template`) showed up as a
choice for "generate a detection rule from these logs". Picking it produces a
correct but baffling refusal: the model is asked to find `event.action` in a
table that holds rule definitions, and the operator reads that as the product
being broken.

These names are read from the same resolvers the writers use, so renaming an
index via its env var keeps this list correct instead of silently drifting.

NOT listed here — customer-owned sources the product merely READS:
  RST_ALERT_INGEST_INDEX          the customer's Kibana detection alerts
  RST_BASELINE_OSQUERY_INDEX      logs-osquery_manager.result-* (osquery output)
Those must stay pickable.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("rst.owned_indices")


def owned_index_names() -> set[str]:
    """Concrete index names this product writes to. Never raises: a module that
    fails to import must not take the index picker down with it."""
    names: set[str] = set()

    def add(fn) -> None:
        try:
            v = fn()
        except Exception as e:  # noqa: BLE001
            logger.debug("owned index resolver failed (%s)", e)
            return
        if isinstance(v, str) and v.strip():
            names.add(v.strip())

    try:
        from . import analysis_store, audit, conversation, report_scheduler, user_state
        from .alerts import store as alerts_store
        from .baseline import eol_store
        from .baseline import store as baseline_store
        from .notify import config as notify_config
        from .notify import outbox as notify_outbox
    except Exception as e:  # noqa: BLE001
        logger.debug("owned index imports failed (%s)", e)
        return names

    add(analysis_store._index)
    add(audit._index_name)
    add(conversation._es_index)
    add(report_scheduler._index_name)
    add(user_state._index_name)
    add(alerts_store._index)
    add(notify_config._index)
    add(notify_outbox._index)
    # Baseline names are module-level constants, not resolvers.
    for const in (
        getattr(baseline_store, "RULES_INDEX", ""),
        getattr(baseline_store, "RESULTS_INDEX", ""),
        getattr(baseline_store, "RUNS_INDEX", ""),
        getattr(eol_store, "EOL_CATALOG_INDEX", ""),
    ):
        if isinstance(const, str) and const.strip():
            names.add(const.strip())

    return names
