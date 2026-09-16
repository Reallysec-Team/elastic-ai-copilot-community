"""osquery 结果读取单测（TDD）。

纯逻辑: 从 hits 里挑最新一轮(同 @timestamp)的所有行，并抽出结果列。
异步: fetch_rows / list_hosts 用假 execute_search 验证编排。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.baseline import result_reader as rr  # noqa: E402
from backend.baseline.field_detect import FieldMap  # noqa: E402

_FM = FieldMap(host_field="host.name", query_field="osquery.pack_name",
               col_prefix="osquery.", source="detected", confident=True)


def _hit(ts, cols):
    return {"_source": {"@timestamp": ts, "host": {"name": "web01"},
                        "osquery": {"pack_name": "R", **cols}}}


def test_select_latest_rows_keeps_only_newest_run():
    hits = [
        _hit("2026-07-04T10:00:00Z", {"u": "a"}),   # 最新一轮 2 行
        _hit("2026-07-04T10:00:00Z", {"u": "b"}),
        _hit("2026-07-03T10:00:00Z", {"u": "old"}),  # 旧一轮，丢弃
    ]
    rows = rr.select_latest_rows(hits, _FM)
    assert rows == [{"pack_name": "R", "u": "a"}, {"pack_name": "R", "u": "b"}]


def test_select_latest_rows_empty():
    assert rr.select_latest_rows([], _FM) == []


def test_fetch_rows_uses_query_builder_and_reader(monkeypatch):
    captured = {}

    async def _fake_search(index, dsl):
        captured["index"] = index
        captured["dsl"] = dsl
        return {"hits": {"hits": [_hit("2026-07-04T10:00:00Z", {"uid": "0"})]}}

    monkeypatch.setattr(rr, "execute_search", _fake_search)
    monkeypatch.setattr(rr, "get_field_map", lambda: _asyncval(_FM))

    rows = asyncio.run(rr.fetch_rows("web01", "HB-ACC-001"))
    assert rows == [{"pack_name": "R", "uid": "0"}]
    # DSL 必须按 host+rule 过滤
    filters = captured["dsl"]["query"]["bool"]["filter"]
    assert {"term": {"host.name": "web01"}} in filters
    assert {"term": {"osquery.pack_name": "HB-ACC-001"}} in filters


def test_fetch_latest_returns_collected_timestamp(monkeypatch):
    async def _fake_search(index, dsl):
        return {"hits": {"hits": [_hit("2026-07-04T10:00:00Z", {"uid": "0"})]}}

    monkeypatch.setattr(rr, "execute_search", _fake_search)
    monkeypatch.setattr(rr, "get_field_map", lambda: _asyncval(_FM))
    rows, collected = asyncio.run(rr.fetch_latest("web01", "HB-ACC-001"))
    assert rows == [{"pack_name": "R", "uid": "0"}]
    assert collected == "2026-07-04T10:00:00Z"   # engine 据此判新鲜度


def test_fetch_latest_no_hits_has_no_timestamp(monkeypatch):
    async def _fake_search(index, dsl):
        return {"hits": {"hits": []}}

    monkeypatch.setattr(rr, "execute_search", _fake_search)
    monkeypatch.setattr(rr, "get_field_map", lambda: _asyncval(_FM))
    assert asyncio.run(rr.fetch_latest("web01", "R")) == ([], None)


def test_host_last_seen_reads_value_as_string(monkeypatch):
    async def _fake_search(index, dsl):
        # date 字段的 max 聚合：value 是 epoch_millis，只有 value_as_string 可用。
        return {"aggregations": {"last_seen": {"value": 1783166400000.0,
                                               "value_as_string": "2026-07-04T10:00:00Z"}}}

    monkeypatch.setattr(rr, "execute_search", _fake_search)
    monkeypatch.setattr(rr, "get_field_map", lambda: _asyncval(_FM))
    assert asyncio.run(rr.host_last_seen("web01")) == "2026-07-04T10:00:00Z"


def test_host_last_seen_none_when_never_reported(monkeypatch):
    async def _fake_search(index, dsl):
        return {"aggregations": {"last_seen": {"value": None}}}

    monkeypatch.setattr(rr, "execute_search", _fake_search)
    monkeypatch.setattr(rr, "get_field_map", lambda: _asyncval(_FM))
    assert asyncio.run(rr.host_last_seen("ghost")) is None


def test_list_hosts_applies_roster_window(monkeypatch):
    captured = {}

    async def _fake_search(index, dsl):
        captured["dsl"] = dsl
        return {"aggregations": {"hosts": {"buckets": []}}}

    monkeypatch.setenv("RST_BASELINE_HOST_ROSTER_DAYS", "7")
    monkeypatch.setattr(rr, "execute_search", _fake_search)
    monkeypatch.setattr(rr, "get_field_map", lambda: _asyncval(_FM))
    asyncio.run(rr.list_hosts())
    assert captured["dsl"]["query"]["bool"]["filter"] == [
        {"range": {"@timestamp": {"gte": "now-7d"}}}]


def test_list_hosts_reads_agg(monkeypatch):
    async def _fake_search(index, dsl):
        return {"aggregations": {"hosts": {"buckets": [
            {"key": "web01", "doc_count": 5}, {"key": "db01", "doc_count": 3}]}}}

    monkeypatch.setattr(rr, "execute_search", _fake_search)
    monkeypatch.setattr(rr, "get_field_map", lambda: _asyncval(_FM))

    hosts = asyncio.run(rr.list_hosts())
    assert hosts == ["web01", "db01"]


def _asyncval(v):
    async def _f():
        return v
    return _f()


# ── 索引名解析 ────────────────────────────────────────────────────────────
# 读的那个（客户 osquery 原始数据）和写的那个（我们的判定结果，见
# `baseline/store.py` 的 RST_BASELINE_RESULTS_INDEX）原来只差一个 s，方向相反。
# 设错一个，基线页面看起来就是空的。这三条钉住改名后的取值顺序。


def test_osquery_index_env_wins(monkeypatch):
    monkeypatch.setenv("RST_BASELINE_OSQUERY_INDEX", "osquery-demo-*")
    monkeypatch.setenv("RST_BASELINE_RESULT_INDEX", "legacy-*")
    assert rr.result_index() == "osquery-demo-*"


def test_legacy_result_index_env_still_read(monkeypatch):
    monkeypatch.delenv("RST_BASELINE_OSQUERY_INDEX", raising=False)
    monkeypatch.setenv("RST_BASELINE_RESULT_INDEX", "legacy-*")
    assert rr.result_index() == "legacy-*"


def test_result_index_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("RST_BASELINE_OSQUERY_INDEX", raising=False)
    monkeypatch.delenv("RST_BASELINE_RESULT_INDEX", raising=False)
    assert rr.result_index() == rr.DEFAULT_RESULT_INDEX
