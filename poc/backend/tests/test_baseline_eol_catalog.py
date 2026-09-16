"""endoflife.date API payload → eol-catalog doc 的纯转换单测（TDD）。

转换与网络分离：fetch 在 scripts/eol_sync.py（带外网），这里只测纯 transform，
可离线复现。endoflife 的 eol 字段是多态的（日期串 | true | false | 缺失），转换要归一。
"""
from __future__ import annotations

import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.baseline import eol_catalog  # noqa: E402

_SYNCED = "2026-07-04T00:00:00Z"


def test_transform_release_date_eol():
    obj = {"cycle": "8", "eol": "2029-05-31", "releaseDate": "2019-09-24", "latest": "8.10"}
    doc = eol_catalog.transform_release("centos", obj, _SYNCED)
    assert doc["product"] == "centos"
    assert doc["cycle"] == "8"
    assert doc["eol"] == "2029-05-31"
    assert doc["eol_raw"] == "2029-05-31"
    assert doc["release_date"] == "2019-09-24"
    assert doc["latest"] == "8.10"
    assert doc["synced_at"] == _SYNCED
    assert doc["source"] == "endoflife.date"


def test_transform_release_bool_false_eol():
    # eol=false → 仍支持；date 落 None，raw 记 "false"
    obj = {"cycle": "24.04", "eol": False}
    doc = eol_catalog.transform_release("ubuntu", obj, _SYNCED)
    assert doc["eol"] is None
    assert doc["eol_raw"] == "false"


def test_transform_release_bool_true_eol():
    obj = {"cycle": "6", "eol": True}
    doc = eol_catalog.transform_release("centos", obj, _SYNCED)
    assert doc["eol"] is None
    assert doc["eol_raw"] == "true"


def test_transform_release_missing_eol():
    obj = {"cycle": "9"}
    doc = eol_catalog.transform_release("centos", obj, _SYNCED)
    assert doc["eol"] is None
    assert doc["eol_raw"] == ""


def test_transform_release_cycle_coerced_to_str():
    obj = {"cycle": 12, "eol": "2028-06-30"}
    doc = eol_catalog.transform_release("debian", obj, _SYNCED)
    assert doc["cycle"] == "12"


def test_doc_id_is_product_colon_cycle():
    assert eol_catalog.doc_id({"product": "centos", "cycle": "7"}) == "centos:7"


def test_default_products_cover_common_distros():
    prods = set(eol_catalog.DEFAULT_PRODUCTS)
    for p in ("centos", "rhel", "ubuntu", "debian", "almalinux", "rocky"):
        assert p in prods


def test_transform_payload_maps_all_cycles():
    payload = [
        {"cycle": "8", "eol": "2029-05-31"},
        {"cycle": "7", "eol": "2024-06-30"},
    ]
    docs = eol_catalog.transform_payload("centos", payload, _SYNCED)
    assert [d["cycle"] for d in docs] == ["8", "7"]
    assert all(d["product"] == "centos" for d in docs)
