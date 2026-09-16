"""Stage 6 — masked aggregation support.

mask_aggregations walks the ES aggregation RESPONSE in parallel with the
REQUEST aggs spec (which carries each bucket agg's source `field`), and reuses
mask_doc's per-field policy on bucket keys — so counts/stats survive while
identifying values (users, IPs, emails) get masked. Structural keys
(date_histogram time, filters/range labels) pass through; unknown-provenance
keys are defensively masked; top_hits _source is fully masked.
"""
from __future__ import annotations

import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.field_masking import mask_aggregations  # noqa: E402

_CLOUD = "cloud"
_PRIVATE = "private"


def test_terms_bucket_key_masked_by_field_policy():
    req = {"top_users": {"terms": {"field": "user.name"}}}
    resp = {
        "top_users": {
            "buckets": [
                {"key": "administrator", "doc_count": 42},
                {"key": "bo", "doc_count": 7},
            ]
        }
    }
    out = mask_aggregations(resp, req, mode=_CLOUD)
    keys = [b["key"] for b in out["top_users"]["buckets"]]
    # user policy (cloud): len>2 → first+***+last; len<=2 → first+*.
    assert keys == ["a***r", "b*"]
    assert out["top_users"]["buckets"][0]["doc_count"] == 42


def test_ip_terms_key_masked():
    # cloud is the *stronger* tier (data leaves the customer network) → /16;
    # private (self-hosted LLM) keeps one more octet → /24. Same direction as
    # the email/user policies.
    req = {"src": {"terms": {"field": "source.ip"}}}
    resp = {"src": {"buckets": [{"key": "10.1.2.3", "doc_count": 5}]}}
    assert mask_aggregations(resp, req, mode=_CLOUD)["src"]["buckets"][0]["key"] == "10.1.x.x"
    assert mask_aggregations(resp, req, mode=_PRIVATE)["src"]["buckets"][0]["key"] == "10.1.2.x"


def test_metric_value_passes_through():
    req = {"uniq": {"cardinality": {"field": "user.name"}}}
    resp = {"uniq": {"value": 128}}
    out = mask_aggregations(resp, req, mode=_CLOUD)
    assert out["uniq"]["value"] == 128


def test_date_histogram_keys_pass_through():
    req = {"over_time": {"date_histogram": {"field": "@timestamp", "fixed_interval": "1h"}}}
    resp = {
        "over_time": {
            "buckets": [
                {"key": 1720000000000, "key_as_string": "2024-07-03T10:00:00Z", "doc_count": 3},
            ]
        }
    }
    out = mask_aggregations(resp, req, mode=_CLOUD)
    b = out["over_time"]["buckets"][0]
    assert b["key_as_string"] == "2024-07-03T10:00:00Z"   # time label not masked
    assert b["doc_count"] == 3


def test_unknown_field_key_defensively_masked():
    # Response has a bucket agg but the request spec doesn't tell us the field
    # (e.g. malformed / stripped) → we cannot know provenance → mask the key.
    req = {"mystery": {}}
    resp = {"mystery": {"buckets": [{"key": "secret-value", "doc_count": 1}]}}
    out = mask_aggregations(resp, req, mode=_CLOUD)
    assert out["mystery"]["buckets"][0]["key"] == "[AGG_KEY_MASKED]"
    assert out["mystery"]["buckets"][0]["doc_count"] == 1


def test_nested_subagg_key_masked():
    req = {
        "by_host": {
            "terms": {"field": "host.name"},
            "aggs": {"by_user": {"terms": {"field": "user.name"}}},
        }
    }
    resp = {
        "by_host": {
            "buckets": [
                {
                    "key": "web-server-01",
                    "doc_count": 10,
                    "by_user": {"buckets": [{"key": "administrator", "doc_count": 4}]},
                }
            ]
        }
    }
    out = mask_aggregations(resp, req, mode=_CLOUD)
    inner = out["by_host"]["buckets"][0]["by_user"]["buckets"][0]
    assert inner["key"] == "a***r"          # nested user masked too
    assert inner["doc_count"] == 4


def test_top_hits_source_masked():
    req = {"samples": {"top_hits": {"size": 1}}}
    resp = {
        "samples": {
            "hits": {"hits": [{"_id": "1", "_source": {"user.name": "administrator", "msg": "x"}}]}
        }
    }
    out = mask_aggregations(resp, req, mode=_CLOUD)
    src = out["samples"]["hits"]["hits"][0]["_source"]
    assert src["user.name"] == "a***r"


def test_airgapped_passes_everything():
    req = {"top_users": {"terms": {"field": "user.name"}}}
    resp = {"top_users": {"buckets": [{"key": "administrator", "doc_count": 42}]}}
    out = mask_aggregations(resp, req, mode="airgapped")
    assert out["top_users"]["buckets"][0]["key"] == "administrator"
