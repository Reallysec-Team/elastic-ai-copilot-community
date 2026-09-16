"""激活 API 认 .lic 信封 / JSON 包装，不只认裸 token。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.license_state import _unwrap_token  # noqa: E402

TOK = "eyJhcHAiOiJ4In0.c2ln"


def test_bare_token_untouched():
    assert _unwrap_token(f"  {TOK}\n") == TOK


def test_offline_lic_bundle():
    bundle = json.dumps({"fmt": "rstlic-offline-bundle", "v": 1, "token": TOK, "sha256": "x"})
    assert _unwrap_token(bundle) == TOK


def test_online_json_wrapper():
    assert _unwrap_token(json.dumps({"license_token": TOK})) == TOK
    assert _unwrap_token(json.dumps({"license_key": TOK})) == TOK


def test_garbage_json_falls_through():
    assert _unwrap_token('{"nope": 1}') == '{"nope": 1}'
    assert _unwrap_token("{not json") == "{not json"
