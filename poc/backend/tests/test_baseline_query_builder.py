"""确定性 DSL builder 单测（TDD）—— 卡点2 已定：判定取数不走 LLM。

判定引擎对「主机 H + 规则 R」取 osquery 最新结果，DSL 形状固定:
  filter host_field==H AND query_field==R，按时间倒序取一窗口。
必须确定性：同输入必得同 DSL（可复现、可审计）。
"""
from __future__ import annotations

import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.baseline import query_builder as qb  # noqa: E402
from backend.baseline.field_detect import FieldMap  # noqa: E402

_FM = FieldMap(host_field="host.name", query_field="osquery.pack_name",
               col_prefix="osquery.", source="detected", confident=True)


def test_latest_query_filters_host_and_rule():
    dsl = qb.build_latest_query("web01", "HB-ACC-001", _FM)
    filters = dsl["query"]["bool"]["filter"]
    assert {"term": {"host.name": "web01"}} in filters
    assert {"term": {"osquery.pack_name": "HB-ACC-001"}} in filters


def test_latest_query_sorts_desc_by_time():
    dsl = qb.build_latest_query("web01", "HB-ACC-001", _FM)
    assert dsl["sort"] == [{"@timestamp": {"order": "desc"}}]


def test_latest_query_bounded_size():
    dsl = qb.build_latest_query("web01", "HB-ACC-001", _FM, size=250)
    assert dsl["size"] == 250


def test_latest_query_is_deterministic():
    a = qb.build_latest_query("web01", "HB-ACC-001", _FM)
    b = qb.build_latest_query("web01", "HB-ACC-001", _FM)
    assert a == b  # 同输入同输出


def test_hosts_query_aggregates_on_host_field():
    dsl = qb.build_hosts_query(_FM, size=1000)
    assert dsl["size"] == 0  # 只要聚合桶，不要命中文档
    agg = dsl["aggs"]["hosts"]["terms"]
    assert agg["field"] == "host.name"
    assert agg["size"] == 1000


def test_latest_query_has_no_time_lower_bound():
    # 刻意的：加了下界，expect_empty 系规则会把失联主机判成 pass（0 行 = 通过），
    # 比按陈旧数据判定更糟。新鲜度在 engine 判，不在 DSL 里过滤。
    dsl = qb.build_latest_query("web01", "HB-ACC-001", _FM)
    assert not any("range" in f for f in dsl["query"]["bool"]["filter"])


def test_hosts_query_bounds_roster_window():
    dsl = qb.build_hosts_query(_FM, roster_days=30)
    assert {"range": {"@timestamp": {"gte": "now-30d"}}} in dsl["query"]["bool"]["filter"]


def test_hosts_query_roster_window_can_be_disabled():
    assert "query" not in qb.build_hosts_query(_FM, roster_days=0)


def test_host_last_seen_query_maxes_timestamp():
    dsl = qb.build_host_last_seen_query("web01", _FM)
    assert dsl["size"] == 0
    assert {"term": {"host.name": "web01"}} in dsl["query"]["bool"]["filter"]
    assert dsl["aggs"]["last_seen"]["max"]["field"] == "@timestamp"


def test_hosts_query_uses_custom_field_map():
    fm = FieldMap(host_field="agent.id", query_field="q", col_prefix="c.",
                  source="env", confident=True)
    dsl = qb.build_hosts_query(fm)
    assert dsl["aggs"]["hosts"]["terms"]["field"] == "agent.id"
