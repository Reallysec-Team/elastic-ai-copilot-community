"""基线索引 mapping / index_specs 单测（TDD）—— 覆盖新增 eol-catalog。"""
from __future__ import annotations

import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.baseline import indices  # noqa: E402


def test_eol_catalog_mapping_is_strict():
    m = indices.EOL_CATALOG_MAPPING["mappings"]
    assert m["dynamic"] == "strict"
    props = m["properties"]
    assert props["product"]["type"] == "keyword"
    assert props["cycle"]["type"] == "keyword"
    assert props["eol"]["type"] == "date"
    assert props["eol_raw"]["type"] == "keyword"
    assert props["synced_at"]["type"] == "date"
    # eol 是 date 且可空 → 必须允许 null（ignore_malformed 或 null_value 二选一均可，
    # 这里要求 null_value 缺省时至少不因 null 报错：约定写入前把 None 剔除即可，
    # 故 mapping 只需 date 类型存在）
    assert props["source"]["type"] == "keyword"


def test_index_specs_includes_eol_catalog():
    specs = indices.index_specs("r", "res", "run", "eol-cat")
    names = [n for n, _ in specs]
    assert "eol-cat" in names
    assert names == ["r", "res", "run", "eol-cat"]


def test_index_specs_eol_default_name():
    # 不传 eol 索引名时用默认，仍应产出 4 个索引
    specs = indices.index_specs("r", "res", "run")
    assert len(specs) == 4
