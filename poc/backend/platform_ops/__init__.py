"""Platform ops: read-only health checks for the customer's own ELK stack.

Separate from the `_search` query surface on purpose — see `probe.py` for why
this package cannot reuse `validate_dsl` / `index_whitelist` / `mask_doc`.
"""
