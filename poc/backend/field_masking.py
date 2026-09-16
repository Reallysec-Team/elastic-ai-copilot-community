"""Field masking — redact sensitive values before sending to LLM.

Three modes (all available on every deployment; the operator picks one):
  cloud      Strong redaction. For Cloud LLM (OpenAI / Volcengine via internet).
             IPs → /16, emails → ***@domain, auth/cookies/secrets → REDACTED,
             JWT/long hex tokens → REDACTED, phones → REDACTED.
  private    Moderate redaction. For self-hosted LLM (Ollama / vLLM / on-prem).
             IPs → /24, partial email mask (preserve first/last char),
             secrets/auth still REDACTED, hex tokens still REDACTED.

Known gap — usernames in free text are NOT masked. `_mask_by_content` scans
unstructured fields (`message`, `request`, ...) for IPs / emails / secrets, but
not for account names: SSH, sudo and auditd logs write the subject into the
message body, and masking it there would break agentic investigation, which
pivots on the real account name to find the follow-on activity. So the UI can
show `s***p` while the full account name still reaches a cloud LLM through
`message`. Deployments that cannot accept that must run `airgapped`.
  airgapped  No redaction. For fully air-gapped deployment with on-prem LLM.

Mode selection:
  1. RST_MASKING_MODE (set from the settings UI or .env), if valid
  2. default: cloud (safest)

Masking used to be license-gated (cloud on trial, private on standard,
airgapped on enterprise). It is not any more: masking is how a customer
protects its *own* data before it leaves the cluster, and charging a tier to
be *more* careful never made sense — a customer who bypassed the gate to run
airgapped was only protecting itself. All three modes are free.
"""

import ipaddress
import os
import re
from copy import deepcopy
from typing import Any


MODE_CLOUD = "cloud"
MODE_PRIVATE = "private"
MODE_AIRGAPPED = "airgapped"
_VALID_MODES = (MODE_CLOUD, MODE_PRIVATE, MODE_AIRGAPPED)

# Field-name patterns: match a dotted path's last segment(s) to a category.
#
# Boundary token `_B` accepts dot OR underscore so snake_case fields like
# `auth_token`, `user_password`, `customer_credit_card` are caught alongside
# the dotted counterparts (`user.email`, `client.ip`). Previously only `.` was
# accepted, which let snake_case secret/PII fields pass through unmasked.
_B = r"(?:^|[._])"
_FIELD_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(_B + r"(?:client|source|destination|host|server)\.?ip$", re.I), "ip"),
    (re.compile(_B + r"(?:src_?ip|dst_?ip|remote_?addr)$", re.I), "ip"),
    (re.compile(_B + r"ip(?:_address)?$", re.I), "ip"),
    (re.compile(_B + r"(?:user\.email|email|mail|from|to|cc|bcc|sender|recipient)$", re.I), "email"),
    (re.compile(_B + r"(?:user\.?name|username|user|login|account|owner)$", re.I), "user"),
    (re.compile(_B + r"authorization$", re.I), "auth"),
    (re.compile(_B + r"cookie$", re.I), "cookie"),
    (re.compile(
        _B + r"(?:password|passwd|pwd|secret|api_?key|token|access_?token|refresh_?token|"
        r"bearer_?token|id_?token|csrf_?token|session_?id|client_?secret|private_?key)$",
        re.I,
    ), "secret"),
    (re.compile(_B + r"(?:phone|mobile|tel|cellphone)$", re.I), "phone"),
    (re.compile(_B + r"(?:credit_?card|card_?number|ccn|iban|swift)$", re.I), "card"),
    (re.compile(
        _B + r"(?:id_?card|ssn|national_?id|passport|driver_?license|drivers_?license|"
        r"tax_?id|vat_?(?:number|id)|身份证|护照|驾照)$",
        re.I,
    ), "national_id"),
]

# Value-pattern based detection (for unstructured fields like message, request).
#
# `saas_key` covers common provider key prefixes that previously slipped through
# free-text fields: Stripe (sk_live/sk_test, pk_*), AWS access-key (AKIA*),
# GitHub tokens (ghp_/gho_/ghs_/ghu_/ghr_), GitLab PAT (glpat-), Google API
# (AIza...), Slack (xox?-...). 16+ chars body to avoid over-matching.
_VALUE_PATTERNS = {
    "ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    # IPv6 (full, compressed `::`, and embedded-IPv4 forms). Deliberately loose —
    # the substitution callback re-validates every hit with `ipaddress` and leaves
    # non-IPv6 text (e.g. a "12:00:00" timestamp) untouched, so over-matching here
    # cannot corrupt the doc.
    "ipv6": re.compile(
        r"(?<![0-9A-Za-z:.])(?:"
        r"(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}"            # full 8-hextet
        r"|(?:[0-9A-Fa-f]{1,4}:){1,7}:"                        # trailing ::
        r"|(?:[0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}"       # x::x
        r"|(?:[0-9A-Fa-f]{1,4}:){1,5}(?::[0-9A-Fa-f]{1,4}){1,2}"
        r"|(?:[0-9A-Fa-f]{1,4}:){1,4}(?::[0-9A-Fa-f]{1,4}){1,3}"
        r"|(?:[0-9A-Fa-f]{1,4}:){1,3}(?::[0-9A-Fa-f]{1,4}){1,4}"
        r"|(?:[0-9A-Fa-f]{1,4}:){1,2}(?::[0-9A-Fa-f]{1,4}){1,5}"
        r"|[0-9A-Fa-f]{1,4}:(?::[0-9A-Fa-f]{1,4}){1,6}"       # x::...
        r"|:(?:(?::[0-9A-Fa-f]{1,4}){1,7}|:)"                  # leading ::
        r")(?![0-9A-Za-z:.])"
    ),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    # Long hex blobs. NOTE: file hashes (MD5=32, SHA1=40, SHA256=64) are critical
    # IOCs for SOC investigation and must NOT be redacted — the substitution
    # callback (`_redact_long_hex`) passes those standard lengths through and only
    # redacts other-length hex, which is far more likely a raw key/token.
    "long_hex": re.compile(r"\b[a-fA-F0-9]{32,}\b"),
    "auth_header": re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9+/=._-]{8,}"),
    "cn_phone": re.compile(r"\b1[3-9]\d{9}\b"),
    "saas_key": re.compile(
        r"\b(?:"
        r"sk[_-](?:live|test)[_-][A-Za-z0-9]{8,}"          # Stripe live/test secret keys
        r"|pk[_-](?:live|test)[_-][A-Za-z0-9]{8,}"         # Stripe publishable
        r"|sk-[A-Za-z0-9_-]{16,}"                          # OpenAI / Anthropic / Stripe rest-key
        r"|AKIA[0-9A-Z]{16}"                               # AWS access-key ID
        r"|ASIA[0-9A-Z]{16}"                               # AWS session token id
        r"|ghp_[A-Za-z0-9]{20,}"                           # GitHub PAT
        r"|gho_[A-Za-z0-9]{20,}"
        r"|ghs_[A-Za-z0-9]{20,}"
        r"|ghu_[A-Za-z0-9]{20,}"
        r"|ghr_[A-Za-z0-9]{20,}"
        r"|glpat-[A-Za-z0-9_-]{20,}"                       # GitLab PAT
        r"|AIza[0-9A-Za-z_-]{20,}"                         # Google API key
        r"|xox[abprs]-[A-Za-z0-9-]{10,}"                   # Slack token
        r")\b"
    ),
}

# Field-name context hints used to disambiguate a *standard-length* (32/40/64)
# hex value. A bare hex blob of these lengths is ambiguous: it is either a file
# hash (MD5/SHA1/SHA256 — a valuable IOC we must keep) or a raw key/HMAC of the
# same byte-length (16/20/32-byte key hex-encoded — a secret we must redact
# before it reaches the cloud LLM). The substitution callback only sees the
# matched substring, so we plumb the field path through and consult these hints.
_HEX_KEYISH = re.compile(
    r"(?:key|secret|token|password|passwd|pwd|sign|signature|hmac|"
    r"credential|cred|authorization|bearer|nonce|salt|cipher|priv)",
    re.I,
)
_HEX_HASHISH = re.compile(
    r"(?:hash|md5|sha\d*|checksum|digest|fingerprint|etag|imphash|ssdeep|crc)",
    re.I,
)

# Field categories hard-redacted regardless of value type — these can
# legitimately hold a NUMERIC value (ID-card / bank-card / phone stored as int),
# which would otherwise slip past the string-only masking path below.
_NUMERIC_REDACT_CATEGORIES = ("auth", "cookie", "secret", "card", "national_id", "phone")


def current_mode() -> str:
    """Resolve the current masking mode."""
    override = os.environ.get("RST_MASKING_MODE", "").strip().lower()
    if override in _VALID_MODES:
        return override
    return MODE_CLOUD


def available_modes() -> list[str]:
    """Modes the operator may switch among — all of them, on every tier."""
    return [MODE_CLOUD, MODE_PRIVATE, MODE_AIRGAPPED]


def mask_doc(doc: Any, mode: str | None = None) -> Any:
    """Return a deep-copied doc with sensitive values masked per mode."""
    if mode is None:
        mode = current_mode()
    if mode == MODE_AIRGAPPED:
        return doc
    if not isinstance(doc, dict):
        return doc
    out = deepcopy(doc)
    _walk(out, prefix="", mode=mode)
    return out


def mask_text(text: Any, mode: str | None = None) -> Any:
    """Mask a free-text blob leaving the product (a report, a chat card).

    mask_doc keys off field names, which free text does not have, so this runs
    the content-pattern half of the same policy: SaaS keys, JWTs, auth headers,
    long hex secrets, emails, and — in cloud/private — IPs and phone numbers.

    Airgapped passes through, matching mask_doc and mask_alert_for_egress. That
    is the existing product stance for on-prem deployments, not a judgement that
    a third-party destination is safe in that mode.
    """
    if not isinstance(text, str) or not text:
        return text
    if mode is None:
        mode = current_mode()
    if mode == MODE_AIRGAPPED:
        return text
    return _mask_by_content(text, mode)


# ── Aggregation masking ─────────────────────────────────────────────────────
# ES aggregation RESPONSES carry raw field values as bucket `key`s, but the
# response alone doesn't say which field a key came from — that's in the REQUEST
# aggs spec. mask_aggregations walks both in parallel: it reads each bucket
# agg's source `field` from the spec and reuses the exact per-field mask_doc
# policy on the key, so counts/metrics survive while identifying values get
# masked. Without a known field, keys are masked defensively.

# Bucket aggs whose `key` IS a raw field value (must be masked).
_VALUE_BUCKET_AGGS = (
    "terms", "significant_terms", "significant_text", "rare_terms", "multi_terms",
)
# Aggs whose bucket keys are structural / numeric / operator-chosen labels
# (time, ranges, named filters) — not identifying, pass through.
_SAFE_KEY_AGGS = (
    "date_histogram", "histogram", "auto_date_histogram", "variable_width_histogram",
    "date_range", "range", "ip_range", "filters", "filter", "global", "nested",
    "reverse_nested", "sampler", "diversified_sampler", "geo_distance", "geohash_grid",
)

_AGG_KEY_MASK = "[AGG_KEY_MASKED]"


def mask_aggregations(
    resp_aggs: Any, req_aggs: Any, mode: str | None = None
) -> Any:
    """Mask an ES aggregation response using the request aggs spec for field
    provenance. `resp_aggs` = response `aggregations` dict; `req_aggs` = the
    request `aggs` dict. Returns a new masked structure (input untouched)."""
    if mode is None:
        mode = current_mode()
    if mode == MODE_AIRGAPPED or not isinstance(resp_aggs, dict):
        return resp_aggs
    return _mask_aggs_level(resp_aggs, req_aggs if isinstance(req_aggs, dict) else {}, mode)


def _mask_aggs_level(resp: dict, req: dict, mode: str) -> dict:
    out: dict[str, Any] = {}
    for name, body in resp.items():
        spec = req.get(name) if isinstance(req.get(name), dict) else {}
        out[name] = _mask_one_agg(body, spec, mode)
    return out


def _agg_source_field(spec: dict) -> str | None:
    for t in _VALUE_BUCKET_AGGS:
        sub = spec.get(t)
        if isinstance(sub, dict) and isinstance(sub.get("field"), str):
            return sub["field"]
    return None


def _agg_has_safe_keys(spec: dict) -> bool:
    return any(t in spec for t in _SAFE_KEY_AGGS)


def _sub_specs(spec: dict) -> dict:
    sub = spec.get("aggs") or spec.get("aggregations")
    return sub if isinstance(sub, dict) else {}


def _mask_one_agg(body: Any, spec: dict, mode: str) -> Any:
    if not isinstance(body, dict):
        return body
    out = dict(body)

    # top_hits — buckets of full documents; mask each _source.
    hits = out.get("hits")
    if isinstance(hits, dict) and isinstance(hits.get("hits"), list):
        out["hits"] = {
            **hits,
            "hits": [
                {**h, "_source": mask_doc(h.get("_source", {}), mode=mode)}
                if isinstance(h, dict) else h
                for h in hits["hits"]
            ],
        }
        return out

    if "buckets" in out:
        field = _agg_source_field(spec)
        safe = _agg_has_safe_keys(spec)
        out["buckets"] = _mask_buckets(out["buckets"], field, safe, _sub_specs(spec), mode)
        return out

    # Metric agg (value / values / stats) — numeric, pass through.
    return out


def _mask_buckets(buckets: Any, field: str | None, safe: bool, sub: dict, mode: str) -> Any:
    def _fix(b: Any) -> Any:
        if not isinstance(b, dict):
            return b
        nb = dict(b)
        if not safe:
            if "key" in nb:
                nb["key"] = _mask_agg_key(field, nb["key"], mode)
            if "key_as_string" in nb:
                nb["key_as_string"] = _mask_agg_key(field, nb["key_as_string"], mode)
        # Recurse named sub-aggregations present on the bucket.
        for k, v in list(nb.items()):
            if k in sub and isinstance(v, dict):
                nb[k] = _mask_one_agg(v, sub[k], mode)
        return nb

    if isinstance(buckets, list):
        return [_fix(b) for b in buckets]
    if isinstance(buckets, dict):  # keyed buckets (filters keyed=true, ranges)
        return {k: _fix(v) for k, v in buckets.items()}
    return buckets


def _mask_agg_key(field: str | None, key: Any, mode: str) -> Any:
    # Numbers/bools are never identifying on their own — pass through.
    if key is None or isinstance(key, (bool, int, float)):
        return key
    if field is None:
        # Unknown provenance for a string key → cannot apply a field policy;
        # redact rather than risk leaking a raw value.
        return _AGG_KEY_MASK
    masked = mask_doc({field: key}, mode=mode)
    return masked.get(field, _AGG_KEY_MASK) if isinstance(masked, dict) else _AGG_KEY_MASK


def _walk(node: Any, prefix: str, mode: str) -> None:
    if isinstance(node, dict):
        for key in list(node.keys()):
            path = f"{prefix}.{key}" if prefix else key
            v = node[key]
            if isinstance(v, dict):
                _walk(v, path, mode)
            elif isinstance(v, list):
                node[key] = [_mask_in_list(path, item, mode) for item in v]
            else:
                node[key] = _mask_value(path, v, mode)


def _mask_in_list(path: str, item: Any, mode: str) -> Any:
    if isinstance(item, dict):
        _walk(item, path, mode)
        return item
    return _mask_value(path, item, mode)


def _mask_value(path: str, value: Any, mode: str) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if not isinstance(value, str):
        # int / float — a number can still be an ID-card / bank-card / phone /
        # secret value. The string-mask helpers below assume str input, so for
        # non-strings we apply only the hard-redact categories.
        for pattern, category in _FIELD_PATTERNS:
            if category in _NUMERIC_REDACT_CATEGORIES and pattern.search(path):
                return "[REDACTED]"
        return value

    # 1) Field-name driven (more deterministic than content sniffing)
    for pattern, category in _FIELD_PATTERNS:
        if pattern.search(path):
            return _mask_by_category(category, value, mode)

    # 2) Value-pattern driven (catches sensitive content in free-form fields).
    #    `path` is forwarded so the long-hex callback can use field-name context
    #    to tell a file-hash IOC apart from a same-length raw key/HMAC.
    return _mask_by_content(value, mode, path)


def _mask_by_category(category: str, value: str, mode: str) -> str:
    if category == "ip":
        return _mask_ip(value, mode)
    if category == "email":
        return _mask_email(value, mode)
    if category == "user":
        return _mask_user(value, mode)
    if category in ("auth", "cookie", "secret", "card", "national_id"):
        return "[REDACTED]"
    if category == "phone":
        return _mask_phone(value, mode)
    return value


def _mask_by_content(value: str, mode: str, path: str = "") -> str:
    out = value
    # SaaS keys first — they have specific prefixes and would otherwise survive
    # under long_hex (e.g. AKIA0123456789ABCDEF is alpha+digits but not 32 hex).
    out = _VALUE_PATTERNS["saas_key"].sub("[KEY_REDACTED]", out)
    out = _VALUE_PATTERNS["jwt"].sub("[JWT_REDACTED]", out)
    out = _VALUE_PATTERNS["auth_header"].sub("[AUTH_REDACTED]", out)
    out = _VALUE_PATTERNS["long_hex"].sub(lambda m: _redact_long_hex(m, path), out)
    out = _VALUE_PATTERNS["email"].sub(lambda m: _mask_email(m.group(0), mode), out)
    # Mask free-text IPs/phones in both cloud AND private mode, at the mode's own
    # granularity (cloud → /16, private → /24) — this mirrors the field-name-driven
    # path so an IP embedded in a `message` field can't leak past the masker the way
    # a `source.ip` field can't. Airgapped (fully on-prem, trusted LLM) passes through.
    if mode in (MODE_CLOUD, MODE_PRIVATE):
        out = _VALUE_PATTERNS["ipv4"].sub(lambda m: _mask_ip(m.group(0), mode), out)
        out = _VALUE_PATTERNS["ipv6"].sub(lambda m: _mask_ip(m.group(0), mode), out)
        out = _VALUE_PATTERNS["cn_phone"].sub("[PHONE_REDACTED]", out)
    return out


def _redact_long_hex(m: re.Match, path: str = "") -> str:
    """Redact long hex blobs — keep standard file-hash lengths *only* when the
    context does not look like a secret.

    MD5 (32), SHA1 (40) and SHA256 (64) hex digests are file-hash IOCs the SOC
    analyst needs in the LLM context, so those lengths used to be passed through
    unconditionally. But many real secrets are *exactly* those lengths too — a
    16/20/32-byte key hex-encoded, an HMAC, some API tokens — and they were
    leaking to the cloud LLM verbatim.

    Resolution (field-name driven, since the callback otherwise only sees the
    matched substring):
      * Non-standard length      → redact (already implausible as a file hash).
      * Standard length, field name looks key/secret/HMAC-ish (and not also
        hash-ish, e.g. `key_hash`) → redact: treat as a same-length raw secret.
      * Standard length otherwise (explicit hash field, or a generic/free-text
        field such as `message` where we cannot tell) → keep as an IOC.

    Note we deliberately do NOT redact every standard-length hex in free text:
    that would erase the bulk of legitimate hash IOCs. The plugged gap is the
    secret-named field (`signature`, `hmac`, `nonce`, `credential`, ... — those
    not already caught by `_FIELD_PATTERNS`) that happens to be 32/40/64 hex."""
    h = m.group(0)
    if len(h) in (32, 40, 64):
        if _HEX_KEYISH.search(path) and not _HEX_HASHISH.search(path):
            return "[HEX_REDACTED]"
        return h
    return "[HEX_REDACTED]"


def _mask_ip(ip: str, mode: str) -> str:
    # IPv6 (contains a colon) was previously returned verbatim because the
    # split(".") guard below only understood dotted IPv4 — so v6 client/source
    # addresses reached the cloud LLM unmasked. Route them through the v6 masker.
    if ":" in ip:
        return _mask_ipv6(ip, mode)
    parts = ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return ip
    if mode == MODE_CLOUD:
        return f"{parts[0]}.{parts[1]}.x.x"
    if mode == MODE_PRIVATE:
        return f"{parts[0]}.{parts[1]}.{parts[2]}.x"
    return ip


def _mask_ipv6(ip: str, mode: str) -> str:
    """Mask an IPv6 address at the same granularity as IPv4.

    Cloud keeps the first 2 hextets (≈ /32); private, the lighter tier, keeps
    the routing prefix (first 4 hextets ≈ /64) and drops only the host portion.
    Anything that isn't a valid IPv6 literal (e.g. a "12:00" time slipping through the value regex) is
    returned untouched."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if not isinstance(addr, ipaddress.IPv6Address):
        return ip
    groups = addr.exploded.split(":")  # always 8 hextets
    if mode == MODE_CLOUD:
        return ":".join(groups[:2]) + "::x"
    if mode == MODE_PRIVATE:
        return ":".join(groups[:4]) + "::x"
    return ip


def _mask_email(email: str, mode: str) -> str:
    if "@" not in email:
        return email
    local, domain = email.rsplit("@", 1)
    if mode == MODE_CLOUD:
        return f"***@{domain}"
    if mode == MODE_PRIVATE:
        if len(local) <= 2:
            return f"{local[0]}*@{domain}"
        return f"{local[0]}***{local[-1]}@{domain}"
    return email


def _mask_user(value: str, mode: str) -> str:
    if not value:
        return value
    if mode == MODE_CLOUD:
        if len(value) <= 2:
            return value[0] + "*"
        return value[0] + "***" + value[-1]
    if mode == MODE_PRIVATE:
        if len(value) <= 4:
            return value
        return value[:2] + "***" + value[-1]
    return value


def _mask_phone(value: str, mode: str) -> str:
    if mode == MODE_AIRGAPPED:
        return value
    if len(value) >= 7:
        return value[:3] + "****" + value[-4:]
    return "[PHONE_REDACTED]"
