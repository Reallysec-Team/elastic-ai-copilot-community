"""osquery Pack 导出 + query_name 指向单测（方案 C）。

- 规则 query_name 默认 = rule_id（对齐 by construction），可经 collect.query_name 覆盖。
- 导出标准 osquery pack（{queries:{name:{query,interval,snapshot,platform}}}），
  query 名 = query_name，客户一次性导入 Fleet Osquery Manager。
"""
from __future__ import annotations

import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.baseline.schema import Rule  # noqa: E402
from backend.baseline import pack  # noqa: E402


def test_query_name_defaults_to_rule_id():
    r = Rule.from_dict({"rule_id": "HB-ACC-001", "collect": {"query": "SELECT 1;"},
                        "judge": {"operator": "expect_empty"}})
    assert r.query_name == "HB-ACC-001"


def test_query_name_override():
    r = Rule.from_dict({"rule_id": "HB-ACC-001",
                        "collect": {"query": "SELECT 1;", "query_name": "custom_users_check"},
                        "judge": {"operator": "expect_empty"}})
    assert r.query_name == "custom_users_check"


def test_build_pack_shape():
    rules = [
        {"rule_id": "HB-ACC-001", "title": "UID=0", "platform": "linux",
         "collect": {"query": "SELECT username,uid FROM users WHERE uid=0;"},
         "judge": {"operator": "expect_empty"}},
        {"rule_id": "HB-NET-003", "title": "ip_forward", "platform": "linux",
         "collect": {"query": "SELECT current_value FROM system_controls WHERE name='net.ipv4.ip_forward';",
                     "query_name": "ipfwd"},
         "judge": {"operator": "equals"}},
    ]
    p = pack.build_pack(rules, interval=3600)
    q = p["queries"]
    # query 名 = query_name（默认 rule_id / 覆盖后 ipfwd）
    assert set(q.keys()) == {"HB-ACC-001", "ipfwd"}
    assert q["HB-ACC-001"]["query"].startswith("SELECT username")
    assert q["HB-ACC-001"]["interval"] == 3600
    assert q["HB-ACC-001"]["snapshot"] is True          # 基线要当前状态快照
    assert q["HB-ACC-001"]["platform"] == "linux"
    assert q["ipfwd"]["query"].startswith("SELECT current_value")


def test_build_pack_skips_rules_without_query():
    rules = [{"rule_id": "X", "collect": {"query": ""}, "judge": {"operator": "manual_review"}}]
    assert pack.build_pack(rules, interval=3600)["queries"] == {}


def test_build_pack_deterministic():
    rules = [{"rule_id": "A", "collect": {"query": "SELECT 1;"}, "judge": {"operator": "expect_empty"}}]
    assert pack.build_pack(rules, 60) == pack.build_pack(rules, 60)
