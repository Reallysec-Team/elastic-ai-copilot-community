"""Field dictionary / index browser.

Given an index, return:
  - total doc count
  - flat field list with type
  - top sample values per field (terms agg)
  - approximate cardinality per field

Used by the frontend to help users discover fields before forming a question.
Read-only — only ES queries, no LLM call.
"""

import logging
import os
from typing import Any

from . import response_cache
from .es_client import get_es

logger = logging.getLogger("rst.field_dict")


def _cache_ttl() -> float:
    raw = os.environ.get("RST_FIELD_DICT_CACHE_TTL_S", "").strip()
    if raw == "":
        return 300.0  # default: 5 min — mappings/value distributions move slowly
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 300.0

_AGGREGATABLE_TYPES = {
    "keyword", "ip", "boolean",
    "long", "integer", "short", "byte",
    "double", "float", "half_float", "scaled_float",
    "date",
}
_BATCH_SIZE = 30  # how many fields' aggs to bundle into one ES request


async def get_field_dictionary(
    index: str, sample_size: int = 5, max_fields: int = 100
) -> dict[str, Any]:
    es = get_es()

    # The mapping fingerprint is folded into the cache key so a mapping change
    # (new field, reindex) transparently busts stale entries. But get_mapping is
    # a live ES call: if it fails transiently we must NOT lose access to an
    # otherwise-servable cached result. So we keep a fingerprint-LESS fallback
    # key alongside the fingerprinted one and degrade to it when the mapping
    # can't be fetched. Mirrors main.py /api/generate.
    fallback_key = response_cache.make_key("field_dict", index, sample_size, max_fields)

    mapping_body: dict[str, Any] | None = None
    try:
        mapping_resp = await es.indices.get_mapping(index=index)
        mapping_body = mapping_resp.body
    except Exception as e:  # noqa: BLE001
        logger.warning(f"get_mapping failed for {index}, will try cached fallback: {e}")

    if mapping_body is None:
        # Mapping unavailable — best-effort serve the last good result rather
        # than failing a request we could have answered from cache.
        cached = response_cache.get(fallback_key)
        if cached is not None:
            return cached
        # Nothing cached either — surface a clear error from the live call.
        mapping_resp = await es.indices.get_mapping(index=index)
        mapping_body = mapping_resp.body

    cache_key = response_cache.make_key(
        "field_dict",
        index,
        sample_size,
        max_fields,
        response_cache.fingerprint(mapping_body),
    )
    cached = response_cache.get(cache_key)
    if cached is not None:
        return cached

    result = await _build_field_dictionary(index, sample_size, max_fields, mapping_body)
    # Store under both keys: the fingerprinted key drives invalidation, the
    # fallback key backs degraded reads when get_mapping is temporarily down.
    response_cache.set(cache_key, result, ttl=_cache_ttl())
    response_cache.set(fallback_key, result, ttl=_cache_ttl())
    return result


async def _build_field_dictionary(
    index: str, sample_size: int, max_fields: int, mapping: dict[str, Any]
) -> dict[str, Any]:
    es = get_es()

    try:
        count_resp = await es.count(index=index)
        doc_count = count_resp.body.get("count", 0)
    except Exception as e:
        logger.warning(f"count failed for {index}: {e}")
        doc_count = 0

    flat = _flatten_mapping(mapping)

    # Truncate before doing aggs to bound cost
    truncated = len(flat) > max_fields
    field_names = list(flat.keys())[:max_fields]

    fields_with_data: list[dict[str, Any]] = []
    if doc_count > 0 and field_names:
        # Build aggregations in batches — each ES request takes a subset
        for batch_start in range(0, len(field_names), _BATCH_SIZE):
            batch = field_names[batch_start : batch_start + _BATCH_SIZE]
            aggs: dict[str, Any] = {}
            agg_to_field: dict[str, str] = {}
            for i, name in enumerate(batch):
                ftype = flat[name]
                agg_field = _resolve_agg_field(name, ftype, flat)
                if not agg_field:
                    continue
                safe = f"f_{batch_start + i}"
                agg_to_field[safe] = name
                aggs[f"{safe}_terms"] = {
                    "terms": {"field": agg_field, "size": sample_size}
                }
                aggs[f"{safe}_card"] = {
                    "cardinality": {"field": agg_field}
                }
            if not aggs:
                continue
            try:
                resp = await es.search(
                    index=index, body={"size": 0, "aggs": aggs}
                )
                a = resp.body.get("aggregations") or {}
                for safe, name in agg_to_field.items():
                    samples_block = a.get(f"{safe}_terms") or {}
                    buckets = samples_block.get("buckets") or []
                    samples = [
                        {"value": b.get("key_as_string", b.get("key")),
                         "count": b.get("doc_count", 0)}
                        for b in buckets
                    ]
                    card_block = a.get(f"{safe}_card") or {}
                    fields_with_data.append({
                        "name": name,
                        "type": flat[name],
                        "cardinality_approx": card_block.get("value", 0),
                        "samples": samples,
                    })
            except Exception as e:
                logger.warning(f"agg batch {batch_start} failed: {e}")

    seen = {f["name"] for f in fields_with_data}
    for name in field_names:
        if name in seen:
            continue
        fields_with_data.append({
            "name": name,
            "type": flat[name],
            "cardinality_approx": None,
            "samples": [],
        })

    fields_with_data.sort(key=lambda f: f["name"])

    return {
        "index": index,
        "doc_count": doc_count,
        "fields": fields_with_data,
        "truncated": truncated,
        "total_fields_in_mapping": len(flat),
    }


def _flatten_mapping(mapping: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for _index_name, body in mapping.items():
        props = (body.get("mappings") or {}).get("properties") or {}
        _walk(props, "", out)
    return out


def _walk(props: dict[str, Any], prefix: str, out: dict[str, str]) -> None:
    for name, spec in props.items():
        path = f"{prefix}.{name}" if prefix else name
        if "properties" in spec:
            _walk(spec["properties"], path, out)
        else:
            out[path] = spec.get("type", "object")
            for sub_name, sub_spec in (spec.get("fields") or {}).items():
                out[f"{path}.{sub_name}"] = sub_spec.get("type", "keyword")


def _resolve_agg_field(name: str, ftype: str, flat: dict[str, str]) -> str | None:
    if ftype in _AGGREGATABLE_TYPES:
        return name
    if ftype == "text":
        kw = f"{name}.keyword"
        if kw in flat:
            return kw
    return None


# ── Sample values for the NL→DSL prompt ──────────────────────────────────────
#
# The generator used to see only field NAMES and TYPES. That is enough to write
# syntactically valid DSL and not nearly enough to write a CORRECT one: asked for
# "登录失败" against a Windows security index, the model produced
# `match_phrase: {message: "登录失败"}` — a field that does not exist there, and a
# phrase no document contains. The answer it needed was `event.code: 4625`, which
# is discoverable the moment it can see that event.code only ever holds
# 4624 / 4625 / 4740.
#
# The field dictionary already samples those values (and caches them). This
# exposes a masked, bounded subset of that for the prompt.

# Above this many distinct values, the top-N sample stops describing the field
# and starts being a data leak with no explanatory power (source.ip, message,
# @timestamp). Enum-ish fields — event codes, outcomes, severities, actions —
# sit far below it.
_SAMPLE_MAX_CARDINALITY = 50
_SAMPLE_VALUES_PER_FIELD = 8
# Ceiling for the multi-index widening below; `_sampleable` already caps a
# field at 50 distinct values, so this only bounds prompt size.
_SAMPLE_VALUES_MAX = 24
_SAMPLE_MAX_FIELDS = 40


def _sampleable(field: dict[str, Any]) -> bool:
    card = field.get("cardinality_approx")
    if not isinstance(card, int) or card <= 0 or card > _SAMPLE_MAX_CARDINALITY:
        return False
    # A date's "values" are timestamps — a distinct one per document, and the
    # time RANGE (not the samples) is what a query author needs.
    return field.get("type") != "date"


async def sample_values_for_prompt(index: str) -> dict[str, list[str]]:
    """Masked, low-cardinality sample values per field, for the NL→DSL prompt.

    Only enum-like fields are included (see `_sampleable`) — the point is to show
    the model WHICH values a field can hold, not to ship it data.

    Every value goes through `mask_doc` under its own field path, so the prompt
    obeys the same masking policy as every other model-facing payload. In
    airgapped mode that is a no-op; in cloud/private mode the model sees masked
    values, exactly as it does everywhere else.

    Best-effort: returns {} rather than raising, so a field-dictionary failure
    degrades generation to the old name+type prompt instead of breaking it.
    """
    from .field_masking import mask_doc

    # Across several indices the samples are a UNION, and the top-5 cut then
    # drops values that only one source uses. Live: `log.level` over ten ops
    # streams sampled to [info, INFO, warning, information, error] — the Java
    # stream's "ERROR" fell off the end, and the model dutifully filtered on
    # "error", which that index never writes. Zero rows, no error. Widen the
    # sample with the number of indices so every source's spelling survives.
    n_indices = len([s for s in index.split(",") if s.strip()])
    per_field = min(_SAMPLE_VALUES_PER_FIELD * max(n_indices, 1), _SAMPLE_VALUES_MAX)

    try:
        fd = await get_field_dictionary(index, sample_size=per_field)
    except Exception as e:  # noqa: BLE001 — never block generation on this
        logger.warning("sample_values_for_prompt: field dict failed for %s: %s", index, e)
        return {}

    out: dict[str, list[str]] = {}
    for field in fd.get("fields") or []:
        if len(out) >= _SAMPLE_MAX_FIELDS:
            break
        if not _sampleable(field):
            continue
        name = field.get("name")
        if not isinstance(name, str):
            continue
        values: list[str] = []
        for s in (field.get("samples") or [])[:per_field]:
            raw = s.get("value")
            if raw is None:
                continue
            masked = mask_doc({name: raw})
            v = masked.get(name) if isinstance(masked, dict) else raw
            if v is None:
                continue
            values.append(str(v))
        if values:
            out[name] = values
    return out
