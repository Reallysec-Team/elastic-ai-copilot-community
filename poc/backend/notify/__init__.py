"""Feishu (Lark) notification pipeline: config + outbox + provider.

Two producers feed one outbox:
  - report_scheduler  → periodic 巡检报告 delivery
  - alerts ingest     → real-time high-severity alert push

The outbox worker renders a Feishu interactive card, signs it (optional),
POSTs to each target's custom-bot webhook, and retries with backoff. Delivery
is decoupled from generation so a Feishu outage never loses a report/alert.
"""
