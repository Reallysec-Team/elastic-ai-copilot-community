"""CSV import for asset/identity tables — the security boundary. Enforces size +
row caps, a column whitelist, string-only values, and validate-all-then-index
(no partial writes). Keys are built with the SAME normalization the resolver
uses, so import and lookup agree."""

from __future__ import annotations

import csv as _csv
import hashlib
import io
import json
import logging
from typing import Any

from .entity import normalize_host, normalize_ip, normalize_user
from .sources import csv_source

logger = logging.getLogger("rst.enrich.csv_import")

MAX_BYTES = 2_000_000
MAX_ROWS = 50_000

ASSET_COLUMNS = {"name", "criticality", "category", "owner", "department", "host", "ip"}
IDENTITY_COLUMNS = {"name", "criticality", "category", "owner", "department", "user"}


class CsvImportError(ValueError):
    """Raised with a message naming the offending row/column. No partial write."""


def _parse_and_validate(text: str, kind: str) -> list[dict[str, str]]:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise CsvImportError(f"CSV 超过大小上限（{MAX_BYTES} 字节）")
    if kind == "assets":
        allowed = ASSET_COLUMNS
    elif kind == "identities":
        allowed = IDENTITY_COLUMNS
    else:
        raise CsvImportError(f"未知导入类型 '{kind}'（应为 assets / identities）")

    reader = _csv.DictReader(io.StringIO(text))
    cols = set(reader.fieldnames or [])
    unknown = cols - allowed
    if unknown:
        raise CsvImportError(f"包含不允许的列: {', '.join(sorted(unknown))}")

    rows: list[dict[str, str]] = []
    for i, row in enumerate(reader, start=2):  # row 1 is the header
        if len(rows) >= MAX_ROWS:
            raise CsvImportError(f"行数超过上限（{MAX_ROWS}）")
        # string-only: coerce every value to str, drop None keys (short rows)
        clean = {k: str(v) for k, v in row.items() if k in allowed and v is not None}
        if not clean.get("name"):
            raise CsvImportError(f"第 {i} 行缺少 name")
        rows.append(clean)
    return rows


def _to_doc(row: dict[str, str], kind: str) -> dict[str, Any]:
    doc: dict[str, Any] = {k: v for k, v in row.items() if k not in ("host", "ip", "user")}
    if kind == "assets":
        if row.get("host"):
            doc["keys"] = normalize_host(row["host"])
        if row.get("ip"):
            doc["ip"] = normalize_ip(row["ip"])
    else:
        doc["user_key"] = normalize_user(row.get("user", "") or row["name"])
    return doc


def _doc_id(kind: str, doc: dict[str, Any]) -> str:
    """Stable id from the doc's JOIN identity so re-import upserts (not duplicates).
    Assets are identified by their normalized host keys + ip; identities by user_key.
    Name/owner/etc. deliberately excluded — a corrected sheet for the same host
    should REPLACE the old row, not create a second one."""
    if kind == "assets":
        ident = [sorted(doc.get("keys") or []), doc.get("ip") or ""]
    else:
        ident = doc.get("user_key") or ""
    blob = json.dumps(ident, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


async def import_csv(text: str, kind: str, es) -> dict[str, Any]:
    rows = _parse_and_validate(text, kind)  # raises before any write
    index = csv_source.ASSETS_INDEX if kind == "assets" else csv_source.IDENTITIES_INDEX
    ops: list[Any] = []
    for row in rows:
        doc = _to_doc(row, kind)
        ops.append({"index": {"_index": index, "_id": _doc_id(kind, doc)}})
        ops.append(doc)
    if ops:
        resp = await es.bulk(operations=ops, refresh=True)
        result = getattr(resp, "body", resp)
        if isinstance(result, dict) and result.get("errors"):
            raise CsvImportError("部分行索引失败(ES bulk 报错),已中止")
    return {"indexed": len(rows), "index": index}
