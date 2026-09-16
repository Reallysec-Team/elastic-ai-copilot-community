"""Real-time Elastic/Kibana alert ingest.

Two sources land alerts in one store (``.rst_copilot_alerts``):
  - source A: poll tail (PIT + search_after cursor) of the detection-alerts index
  - source B: Kibana webhook connector → POST /api/alerts/ingest (HMAC verified)

Ingested alerts are field-masked, deduped, optionally auto-triaged, streamed to
the UI over SSE, and (when severe) pushed to Feishu via the notify outbox.
"""
