"""Saved-search dashboards.

A dashboard is a list of panels. Each panel describes a query that the
gateway can re-run on demand (no scheduled background fetches in this
release — keep cost bounded; the UI auto-refreshes when visible).

Storage: poc/dashboards.yml — same overlay-friendly shape as settings.yml.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from .validator import validate_dsl

logger = logging.getLogger("rst.dashboards")

DEFAULT_PATH = Path(__file__).parent.parent / "dashboards.yml"


def _path() -> Path:
    raw = os.environ.get("RST_DASHBOARDS_FILE", "").strip()
    return Path(raw) if raw else DEFAULT_PATH


def load() -> list[dict[str, Any]]:
    p = _path()
    if not p.exists():
        return []
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"failed to read {p}: {e}")
        return []
    panels = data.get("panels") or []
    out: list[dict[str, Any]] = []
    for raw_panel in panels:
        if not isinstance(raw_panel, dict):
            continue
        out.append(_normalize(raw_panel))
    return out


def save(panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = [_validate(p) for p in panels]
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        yaml.safe_dump({"panels": cleaned}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    logger.info(f"dashboards saved — {len(cleaned)} panel(s) → {p}")
    return cleaned


def _validate(p: dict[str, Any]) -> dict[str, Any]:
    pid = (p.get("id") or "").strip()
    if not pid:
        raise ValueError("panel missing 'id'")
    title = (p.get("title") or "").strip()
    if not title:
        raise ValueError(f"panel '{pid}' missing 'title'")
    index = (p.get("index") or "").strip()
    if not index:
        raise ValueError(f"panel '{pid}' missing 'index'")
    dsl = p.get("dsl")
    if not isinstance(dsl, dict):
        raise ValueError(f"panel '{pid}' missing 'dsl' (must be object)")
    # Reject forbidden DSL keys (script/update/delete/…) at store time rather
    # than relying on /api/execute to catch it only when the panel later runs.
    try:
        validate_dsl(dsl)
    except ValueError as e:
        raise ValueError(f"panel '{pid}' has invalid dsl: {e}")
    panel_type = (p.get("type") or "count").strip()
    if panel_type not in {"count", "agg-bar", "table"}:
        raise ValueError(f"panel '{pid}' has unsupported type '{panel_type}'")
    return _normalize(p)


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(raw.get("id") or ""),
        "title": str(raw.get("title") or ""),
        "description": str(raw.get("description") or ""),
        "index": str(raw.get("index") or ""),
        "type": str(raw.get("type") or "count"),
        "dsl": raw.get("dsl") if isinstance(raw.get("dsl"), dict) else {},
        "auto_refresh_seconds": int(raw.get("auto_refresh_seconds") or 0),
        "agg_path": str(raw.get("agg_path") or "by_status"),
    }
