"""endoflife.date API payload → eol-catalog doc 的纯转换。

与网络分离：fetch 在 scripts/eol_sync.py（带外网、可跳过），本模块只做纯转换，
离线可测、可复现。endoflife 的 `eol` 字段多态（日期串 | true | false | 缺失），
在这里归一：
  - 真日期串   → eol=日期, eol_raw=日期
  - true       → eol=None, eol_raw="true"（已 EOL，无具体日期）
  - false      → eol=None, eol_raw="false"（仍支持）
  - 缺失/其它   → eol=None, eol_raw=""

同理 releaseDate 只在是日期串时落 release_date（date 字段不吃 bool/null）。
"""
from __future__ import annotations

from typing import Any

SOURCE = "endoflife.date"

# 首批常见发行版 slug（endoflife.date 产品名）。客户内网同步时按此拉取。
DEFAULT_PRODUCTS: tuple[str, ...] = (
    "centos",
    "rhel",
    "ubuntu",
    "debian",
    "almalinux",
    "rocky",
    "amazon-linux",
    "oracle-linux",
    "sles",
    "opensuse-leap",
    "fedora",
)


def _is_date_str(v: Any) -> bool:
    """粗判 YYYY-MM-DD（endoflife 日期形态）。严格解析留给判定期 compare_eol。"""
    if not isinstance(v, str):
        return False
    parts = v.split("-")
    return len(parts) == 3 and all(p.isdigit() for p in parts)


def _normalize_eol(raw: Any) -> tuple[str | None, str]:
    """endoflife eol 多态值 → (eol_date_or_none, eol_raw)。"""
    if isinstance(raw, bool):
        return None, ("true" if raw else "false")
    if _is_date_str(raw):
        return raw, raw
    if isinstance(raw, str) and raw.strip().lower() in ("true", "false"):
        return None, raw.strip().lower()
    return None, ""


def _date_or_none(v: Any) -> str | None:
    return v if _is_date_str(v) else None


def transform_release(product: str, obj: dict[str, Any], synced_at: str) -> dict[str, Any]:
    """一个 endoflife cycle 对象 → 一条 eol-catalog doc（不可变构造）。"""
    eol_date, eol_raw = _normalize_eol(obj.get("eol"))
    return {
        "product": product,
        "cycle": str(obj.get("cycle", "")),
        "eol": eol_date,
        "eol_raw": eol_raw,
        "release_date": _date_or_none(obj.get("releaseDate")),
        "latest": str(obj.get("latest") or ""),
        "synced_at": synced_at,
        "source": SOURCE,
    }


def transform_payload(product: str, payload: list[dict[str, Any]], synced_at: str) -> list[dict[str, Any]]:
    """整个产品的 cycle 列表 → doc 列表。"""
    return [transform_release(product, obj, synced_at) for obj in (payload or [])]


def doc_id(doc: dict[str, Any]) -> str:
    """幂等文档 id = product:cycle。"""
    return f"{doc['product']}:{doc['cycle']}"
