"""Prometheus metrics for the gateway — scraped at GET /metrics.

Intentionally small. The HTTP request counter + latency histogram cover
error-rate and latency for every endpoint, including the LLM-backed
`/api/generate*` and the ES-backed query endpoints — that is what an
operator alerts on. The license gauge lets ops alert when the license
stops being usable.

Alerting starting points (PromQL):
  * 5xx rate:
      sum(rate(rst_http_requests_total{status=~"5.."}[5m]))
        / sum(rate(rst_http_requests_total[5m]))   > 0.05
  * p99 latency:
      histogram_quantile(0.99,
        sum by (le) (rate(rst_http_request_duration_seconds_bucket[5m]))) > 30
  * license not usable:
      rst_license_usable == 0
"""
from prometheus_client import Counter, Gauge, Histogram

http_requests = Counter(
    "rst_http_requests_total",
    "Gateway HTTP requests by method, route template, and status code.",
    ["method", "path", "status"],
)

http_latency = Histogram(
    "rst_http_request_duration_seconds",
    "Gateway HTTP request duration by method and route template.",
    ["method", "path"],
)

license_usable = Gauge(
    "rst_license_usable",
    "1 when the license is usable (valid / expiring / grace), else 0.",
)
