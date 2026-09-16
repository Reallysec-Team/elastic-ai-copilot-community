"""Build Kibana Discover deep-links from an Elasticsearch DSL query.

This module:
  * Resolves the Kibana data view (index-pattern) saved-object id for a given
    index name via Kibana's saved_objects API. Resolved IDs are cached in a
    module-level dict.
  * Translates a (subset of) Elasticsearch query DSL into KQL.
  * Lifts any range on @timestamp into Discover's `_g.time.from/to` instead of
    embedding it in the KQL query string.
  * Returns a `_g` + `_a` URL for /app/discover.

Anything we cannot translate is silently dropped from the KQL string and
reported back via the `unsupported` list in the response.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import quote

import httpx
from starlette.requests import Request


KIBANA_URL_DEFAULT = "http://localhost:5601"

# index name -> saved-object id (data view id). Process-lifetime cache,
# size-capped so an unbounded set of distinct index names can't grow it forever.
_DATA_VIEW_CACHE: dict[str, str] = {}
_MAX_DATA_VIEW_CACHE = 512


def _kibana_url() -> str:
    """Internal Kibana URL — used for server-side calls (saved_objects API).

    Defaults to the value the gateway uses to talk to Kibana over the docker
    network ("http://kibana:5601" in compose).
    """
    return os.environ.get("KIBANA_URL", KIBANA_URL_DEFAULT).rstrip("/")


def configured_kibana_url() -> str:
    """The raw KIBANA_URL as configured, or "" when unset.

    Unlike `_kibana_url()` this does NOT fall back to the compose default —
    callers reporting a connection failure need to distinguish "pointed at the
    wrong host" from "never configured", which the default would paper over.
    """
    return (os.environ.get("KIBANA_URL") or "").strip().rstrip("/")


def _kibana_auth() -> tuple[dict[str, str], tuple[str, str] | None]:
    """Auth for server-side Kibana calls: (extra_headers, basic_auth_or_None).

    A secured customer Kibana rejects the saved_objects API with 401 unless we
    authenticate. Resolution priority:
      1. KIBANA_API_KEY  → Authorization: ApiKey <key>
      2. KIBANA_USER / KIBANA_PASSWORD → HTTP basic auth
      3. ES_USER / ES_PASSWORD → same Elastic creds (usual single-stack case)
    """
    api_key = os.environ.get("KIBANA_API_KEY", "").strip()
    if api_key:
        return {"Authorization": f"ApiKey {api_key}"}, None
    user = os.environ.get("KIBANA_USER") or os.environ.get("ES_USER")
    password = os.environ.get("KIBANA_PASSWORD") or os.environ.get("ES_PASSWORD")
    if user and password:
        return {}, (user, password)
    return {}, None


logger = logging.getLogger("rst.kibana_link")


def trusted_origin(request: Request) -> str | None:
    """请求头里那个可以拿来推 Kibana 主机名的 Origin/Referer，不可信就 None。

    `public_kibana_url` 会用它的 hostname 拼出 `http://<host>:5601/...`，而这串
    URL 是要发回界面、让人去点的，里面还带着这次查询的 KQL。Origin 是请求方给的：
    `Origin: http://evil.example` 就能让网关生成一条指向别人主机的深链。所以只认
    两种来源 —— 与本网关自己的 Host 同源（正常浏览器就是这一种），或者管理员在
    RST_CORS_ORIGINS 里点过名的前端主机。其余一律当没给，回落到 KIBANA_URL /
    KIBANA_PUBLIC_URL。

    和 csrf.py 判同源用的是同一条规则（host:port，不比 scheme —— TLS 在 Caddy
    那儿终结，网关看到的永远是 http）。
    """
    origin = (request.headers.get("origin") or request.headers.get("referer") or "").strip()
    if not origin:
        return None
    from urllib.parse import urlsplit

    try:
        netloc = urlsplit(origin).netloc.lower()
    except ValueError:
        return None
    if not netloc:
        return None
    allowed = {
        urlsplit(o.strip()).netloc.lower()
        for o in os.environ.get("RST_CORS_ORIGINS", "").split(",")
        if o.strip()
    }
    allowed.discard("")
    host = (request.headers.get("host") or "").strip().lower()
    if host:
        allowed.add(host)
    if netloc not in allowed:
        logger.warning("kibana_link_origin_ignored",
                       extra={"origin": origin[:120], "host": host})
        return None
    return origin


def origin_ignored(request: Request) -> bool:
    """请求带了 Origin/Referer，但它不可信 —— 深链会退回内部主机名。

    界面上要说得出这件事：链接生成了、但点开可能连不上，而原因（「你是从一个
    这个网关不认识的地址访问的」）只写在网关日志里的话，运维只会看到一条打不开
    的链接。
    """
    raw = (request.headers.get("origin") or request.headers.get("referer") or "").strip()
    return bool(raw) and trusted_origin(request) is None


def public_kibana_url(request_origin: str | None = None) -> str:
    """Browser-reachable Kibana URL — used when rendering deep-links to the user.

    Resolution priority:
      1. KIBANA_PUBLIC_URL env (explicit operator config)
      2. derive from caller's Origin: same hostname, port 5601
      3. fall back to KIBANA_URL (only valid in local dev where the gateway
         and the browser share a hostname like 127.0.0.1)

    The fallback is what shipped previously and broke any setup where the
    gateway's KIBANA_URL was an internal docker hostname like 'kibana:5601'.
    """
    pub = os.environ.get("KIBANA_PUBLIC_URL", "").strip()
    if pub:
        return pub.rstrip("/")
    if request_origin:
        try:
            from urllib.parse import urlparse
            p = urlparse(request_origin)
            if p.hostname:
                # Most local/dev compose stacks expose Kibana on the same host
                # as the gateway on port 5601. This is a sane default; operators
                # who run Kibana behind a real domain should set KIBANA_PUBLIC_URL.
                return f"{p.scheme or 'http'}://{p.hostname}:5601"
        except Exception:
            pass
    return _kibana_url()


# ───────────────────────── data view resolution ─────────────────────────


class DataViewNotFound(Exception):
    """Raised when no matching Kibana data view is found for an index."""


# Kibana's alerts-as-data indices are written through an alias; a search hit
# reports the concrete backing index behind it, e.g.
#   alias   .alerts-security.alerts-default
#   backing .internal.alerts-security.alerts-default-000015
# Nobody creates a data view against the backing name — it changes on every
# rollover — so resolution has to fall back to the alias it belongs to.
_BACKING_INDEX_RE = re.compile(r"^\.internal\.(?P<alias>.+)-\d{6,}$")


def alias_of_backing_index(index: str) -> str | None:
    """The alias a Kibana backing index belongs to, or None if not one.

    The `.internal.` prefix stands in for the alias's own leading dot, so it
    has to be put back: `.internal.alerts-security.alerts-default-000015`
    belongs to `.alerts-security.alerts-default`, not `alerts-security...`.
    """
    m = _BACKING_INDEX_RE.match(index or "")
    return f".{m.group('alias')}" if m else None


async def resolve_data_view_id(index: str) -> str:
    """Look up a Kibana data view (index-pattern saved object) id by title.

    Caches successful resolutions in `_DATA_VIEW_CACHE`. Misses are NOT cached
    so the user can fix the issue in Kibana and retry.

    A concrete alerts backing index falls back to its alias, since that is what
    an operator actually creates a data view against.
    """
    if index in _DATA_VIEW_CACHE:
        return _DATA_VIEW_CACHE[index]

    alias = alias_of_backing_index(index)
    if alias:
        try:
            dv_id = await _find_data_view_id(index)
        except DataViewNotFound:
            # Retry under the alias. Cache the result against the ORIGINAL key
            # too, so alerts already stored with a backing-index name don't pay
            # the double lookup on every open.
            dv_id = await _find_data_view_id(alias)
        _remember_data_view(index, dv_id)
        return dv_id

    dv_id = await _find_data_view_id(index)
    _remember_data_view(index, dv_id)
    return dv_id


async def _find_data_view_id(index: str) -> str:
    """One Kibana saved-object lookup. Raises DataViewNotFound on a miss."""
    url = f"{_kibana_url()}/api/saved_objects/_find"
    params = {
        "type": "index-pattern",
        "search_fields": "title",
        "search": index,
        "per_page": 100,
    }
    extra_headers, basic_auth = _kibana_auth()
    headers = {"kbn-xsrf": "true", **extra_headers}

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, params=params, headers=headers, auth=basic_auth)
        r.raise_for_status()
        body = r.json()

    saved = body.get("saved_objects") or []
    # Kibana's `search` is fuzzy on title — pick an exact title match if present,
    # otherwise the first one whose title pattern matches the index literally.
    exact = None
    contains = None
    for so in saved:
        title = (so.get("attributes") or {}).get("title", "")
        if title == index:
            exact = so
            break
        if contains is None and (title == index or _pattern_matches(title, index)):
            contains = so
    chosen = exact or contains
    if not chosen:
        raise DataViewNotFound(
            f"在 Kibana 中找不到匹配索引 '{index}' 的 Data View。"
            f"请先在 Kibana → Stack Management → Data Views 中创建一个 title 为 '{index}'（或匹配该索引的）数据视图。"
        )

    dv_id = chosen.get("id")
    if not dv_id:
        raise DataViewNotFound(f"Kibana 返回的 data view 缺少 id 字段：{chosen!r}")
    return dv_id


def _remember_data_view(index: str, dv_id: str) -> None:
    if len(_DATA_VIEW_CACHE) >= _MAX_DATA_VIEW_CACHE:
        # Evict the oldest entry (dict preserves insertion order).
        _DATA_VIEW_CACHE.pop(next(iter(_DATA_VIEW_CACHE)), None)
    _DATA_VIEW_CACHE[index] = dv_id


def _pattern_matches(pattern: str, index: str) -> bool:
    """True if a Kibana index-pattern title (which may contain `*`) matches `index`."""
    if "*" not in pattern:
        return pattern == index
    # Treat * as a simple wildcard
    import fnmatch
    return fnmatch.fnmatchcase(index, pattern)


# ───────────────────────── DSL → KQL translation ─────────────────────────


# Operators supported on `_g.time` (only @timestamp ranges).
_TIME_FIELD = "@timestamp"


def _kql_escape_value(v: Any) -> str:
    """Escape and quote a scalar for use as a KQL value."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    # KQL: backslash-escape special chars, then wrap in quotes if needed.
    # `:` MUST trigger quoting — an unquoted colon in a value (e.g. a "12:00"
    # time or an IPv6 literal) is parsed by KQL as a field:value separator and
    # corrupts the generated query. `{ }` are reserved too.
    needs_quote = any(ch in s for ch in ' \t(){}:<>"*\\')
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    if needs_quote or s == "" or any(ch.isspace() for ch in s):
        return f'"{s}"'
    return s


def _rison_quote(s: str) -> str:
    """Encode a string as a rison single-quoted literal.

    rison escapes `!` as `!!` and `'` as `!'` inside a quoted string. The order
    matters — `!` must be doubled first so the `!` we introduce for `'` isn't
    re-escaped. The caller percent-encodes the surrounding blob for URL transport;
    Kibana percent-decodes, then rison-parses this back to the original string.
    """
    return "'" + s.replace("!", "!!").replace("'", "!'") + "'"


def _kql_field(name: str) -> str:
    """KQL field reference. Dots are fine; quote if it has weird chars."""
    if any(ch in name for ch in ' \t():<>"*\\'):
        return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return name


def _wrap_paren(expr: str) -> str:
    if not expr:
        return expr
    if expr.startswith("(") and expr.endswith(")"):
        return expr
    return f"({expr})"


def dsl_to_kql(dsl: dict) -> tuple[str, dict[str, str] | None, list[str]]:
    """Translate a DSL `query` clause into (kql, time_range, unsupported).

    `dsl` is the full DSL body — we look at `dsl.get("query")`.
    `time_range` is `{"from": "...", "to": "..."}` if a range on @timestamp was
    found and lifted, otherwise None.
    `unsupported` is a list of human-readable notes about clauses we dropped.
    """
    unsupported: list[str] = []
    time_range: dict[str, str] | None = None

    query = (dsl or {}).get("query") or {}

    def visit(node: Any, path: str = "query") -> str:
        nonlocal time_range
        if not isinstance(node, dict) or not node:
            return ""

        # Single-key clause (the common ES shape)
        if len(node) == 1:
            (k, v), = node.items()
        else:
            # Multiple keys at the same level — translate each, AND them together.
            parts = [visit({kk: vv}, path) for kk, vv in node.items()]
            parts = [p for p in parts if p]
            return " and ".join(parts)

        if k == "match_all":
            return ""
        if k == "match_none":
            return "not *"

        if k == "bool":
            return _visit_bool(v or {}, path + ".bool")

        if k in ("term", "match", "match_phrase"):
            # { field: value } or { field: { value: ..., ... } }
            if not isinstance(v, dict) or len(v) != 1:
                unsupported.append(f"{path}.{k}: 期望单字段对象")
                return ""
            (field, val), = v.items()
            if isinstance(val, dict):
                val = val.get("query", val.get("value"))
            return f"{_kql_field(field)} : {_kql_escape_value(val)}"

        if k == "terms":
            if not isinstance(v, dict):
                unsupported.append(f"{path}.terms: 非对象")
                return ""
            # Strip the option keys
            entries = [(kk, vv) for kk, vv in v.items() if kk not in ("boost", "_name")]
            if len(entries) != 1:
                unsupported.append(f"{path}.terms: 期望单字段")
                return ""
            field, vals = entries[0]
            if not isinstance(vals, list) or not vals:
                unsupported.append(f"{path}.terms.{field}: 非数组或为空")
                return ""
            ored = " or ".join(f"{_kql_field(field)} : {_kql_escape_value(x)}" for x in vals)
            return f"({ored})"

        if k == "prefix":
            if not isinstance(v, dict) or len(v) != 1:
                unsupported.append(f"{path}.prefix: 期望单字段对象")
                return ""
            (field, val), = v.items()
            if isinstance(val, dict):
                val = val.get("value")
            return f"{_kql_field(field)} : {_kql_escape_value(str(val) + '*')}"

        if k == "wildcard":
            if not isinstance(v, dict) or len(v) != 1:
                unsupported.append(f"{path}.wildcard: 期望单字段对象")
                return ""
            (field, val), = v.items()
            if isinstance(val, dict):
                val = val.get("value", val.get("wildcard"))
            return f"{_kql_field(field)} : {_kql_escape_value(val)}"

        if k == "range":
            if not isinstance(v, dict) or len(v) != 1:
                unsupported.append(f"{path}.range: 期望单字段对象")
                return ""
            (field, spec), = v.items()
            if not isinstance(spec, dict):
                unsupported.append(f"{path}.range.{field}: 非对象")
                return ""
            # @timestamp → lift to _g.time
            if field == _TIME_FIELD:
                tr = _range_to_time(spec)
                if tr is None:
                    unsupported.append(f"{path}.range.@timestamp: 无可用 gte/gt/lte/lt")
                    return ""
                # If a previous time range was already lifted, keep the most
                # restrictive-ish — last one wins to keep things simple.
                time_range = tr
                return ""
            return _range_numeric_kql(field, spec, path, unsupported)

        if k == "exists":
            field = v.get("field") if isinstance(v, dict) else None
            if not field:
                unsupported.append(f"{path}.exists: 缺 field")
                return ""
            return f"{_kql_field(field)} : *"

        unsupported.append(f"{path}.{k}: 不支持，已忽略")
        return ""

    def _visit_bool(b: dict, path: str) -> str:
        nonlocal time_range
        must_parts: list[str] = []
        should_parts: list[str] = []
        not_parts: list[str] = []

        def collect(key: str, into: list[str]):
            v = b.get(key)
            if v is None:
                return
            items = v if isinstance(v, list) else [v]
            for i, item in enumerate(items):
                kql = visit(item, f"{path}.{key}[{i}]")
                if kql:
                    into.append(kql)

        collect("must", must_parts)
        collect("filter", must_parts)
        collect("should", should_parts)
        collect("must_not", not_parts)

        and_clauses: list[str] = []
        and_clauses.extend(must_parts)
        if should_parts:
            if len(should_parts) == 1:
                and_clauses.append(should_parts[0])
            else:
                and_clauses.append("(" + " or ".join(_wrap_paren(p) for p in should_parts) + ")")
        for n in not_parts:
            and_clauses.append(f"not {_wrap_paren(n)}")

        if not and_clauses:
            return ""
        if len(and_clauses) == 1:
            return and_clauses[0]
        return " and ".join(_wrap_paren(c) if " or " in c or " and " in c else c for c in and_clauses)

    kql = visit(query, "query")
    return kql, time_range, unsupported


def _range_to_time(spec: dict) -> dict[str, str] | None:
    """Convert an ES range spec on @timestamp to {from, to} for Kibana's _g.time."""
    frm = spec.get("gte", spec.get("gt"))
    to = spec.get("lte", spec.get("lt"))
    if frm is None and to is None:
        return None
    out: dict[str, str] = {}
    out["from"] = str(frm) if frm is not None else "now-90d"
    out["to"] = str(to) if to is not None else "now"
    return out


def _range_numeric_kql(field: str, spec: dict, path: str, unsupported: list[str]) -> str:
    """Render `field >= X and field <= Y` style KQL for numeric ranges."""
    parts: list[str] = []
    f = _kql_field(field)
    if "gte" in spec:
        parts.append(f"{f} >= {_kql_escape_value(spec['gte'])}")
    elif "gt" in spec:
        parts.append(f"{f} > {_kql_escape_value(spec['gt'])}")
    if "lte" in spec:
        parts.append(f"{f} <= {_kql_escape_value(spec['lte'])}")
    elif "lt" in spec:
        parts.append(f"{f} < {_kql_escape_value(spec['lt'])}")
    if not parts:
        unsupported.append(f"{path}.range.{field}: 无可用 gte/gt/lte/lt")
        return ""
    if len(parts) == 1:
        return parts[0]
    return "(" + " and ".join(parts) + ")"


# ───────────────────────── URL building ─────────────────────────


def build_discover_url(
    data_view_id: str,
    kql: str,
    time_range: dict[str, str] | None,
    *,
    request_origin: str | None = None,
) -> str:
    """Build a /app/discover deep-link the BROWSER can reach.

    Uses `public_kibana_url(request_origin)` rather than the internal
    KIBANA_URL — otherwise users behind a docker-compose setup get a link
    like "http://kibana:5601/..." which their browser cannot resolve.
    """
    tr = time_range or {"from": "now-90d", "to": "now"}
    # Build VALID rison first (string values rison-escaped), then percent-encode
    # each whole blob for URL transport. Kibana percent-decodes the fragment
    # BEFORE rison-parsing, so percent-encoding alone never protects the rison
    # single-quote delimiters — a value like a username `d'angelo` would
    # otherwise terminate the rison string early and yield a blank Discover.
    g = (
        f"(time:(from:{_rison_quote(str(tr['from']))},"
        f"to:{_rison_quote(str(tr['to']))}))"
    )
    a = (
        f"(index:{_rison_quote(data_view_id)},"
        f"query:(language:kuery,query:{_rison_quote(kql)}))"
    )
    _g = quote(g, safe="")
    _a = quote(a, safe="")
    return f"{public_kibana_url(request_origin)}/app/discover#/?_g={_g}&_a={_a}"


# ───────────────────────── public entry point ─────────────────────────


async def build_kibana_link(
    index: str, dsl: dict, *, request_origin: str | None = None
) -> dict:
    """Resolve data view + translate DSL + return a Discover URL.

    `request_origin` is the caller's `Origin` (or `Host`) header — used to
    derive a browser-reachable Kibana URL when KIBANA_PUBLIC_URL isn't set.

    Returns a dict like::
        {"url": "...", "kql": "...", "time": {...}, "unsupported": [...]}

    Raises `DataViewNotFound` if no matching data view exists.
    """
    dv_id = await resolve_data_view_id(index)
    kql, time_range, unsupported = dsl_to_kql(dsl or {})
    url = build_discover_url(dv_id, kql, time_range, request_origin=request_origin)
    return {
        "url": url,
        "kql": kql,
        "time": time_range or {"from": "now-90d", "to": "now"},
        "unsupported": unsupported,
    }
