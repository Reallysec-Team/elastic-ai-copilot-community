"""Platform-ops checks: deterministic verdicts over mocked probe results.

No real ES call — every test monkeypatches the named functions in
`backend.platform_ops.probe`, mirroring test_solutions.py's style. The goal
is to lock in the judgment calls found from real local-cluster behavior
(single-node yellow is expected, not a fault) so a future refactor can't
silently flip them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.platform_ops import checks, probe  # noqa: E402
from backend.index_whitelist import IndexWhitelist  # noqa: E402


def _health(status, n_nodes=1, unassigned=0, active_pct=100.0):
    return {
        "status": status,
        "number_of_data_nodes": n_nodes,
        "unassigned_shards": unassigned,
        "active_shards_percent_as_number": active_pct,
    }


@pytest.mark.asyncio
async def test_single_node_yellow_is_warn_not_fail(monkeypatch):
    monkeypatch.setattr(probe, "cluster_health", lambda: _ok(_health("yellow", n_nodes=1, unassigned=7)))
    result = await checks.check_cluster_health()
    assert result["verdict"] == checks.WARN
    assert "单节点" in result["summary"]


@pytest.mark.asyncio
async def test_multi_node_yellow_is_fail(monkeypatch):
    monkeypatch.setattr(probe, "cluster_health", lambda: _ok(_health("yellow", n_nodes=3, unassigned=2)))
    result = await checks.check_cluster_health()
    assert result["verdict"] == checks.FAIL


@pytest.mark.asyncio
async def test_red_is_fail(monkeypatch):
    monkeypatch.setattr(probe, "cluster_health", lambda: _ok(_health("red", n_nodes=3)))
    result = await checks.check_cluster_health()
    assert result["verdict"] == checks.FAIL


@pytest.mark.asyncio
async def test_green_is_ok(monkeypatch):
    monkeypatch.setattr(probe, "cluster_health", lambda: _ok(_health("green", n_nodes=3)))
    result = await checks.check_cluster_health()
    assert result["verdict"] == checks.OK


@pytest.mark.asyncio
async def test_unassigned_shards_skipped_when_not_a_real_problem(monkeypatch):
    called = {"cat_shards": False}

    async def fake_cat_shards():
        called["cat_shards"] = True
        return [], None

    monkeypatch.setattr(probe, "cat_shards", fake_cat_shards)
    result = await checks.check_unassigned_shards(is_real_problem=False)
    assert result["verdict"] == checks.OK
    assert called["cat_shards"] is False


@pytest.mark.asyncio
async def test_unassigned_shards_digs_when_real_problem(monkeypatch):
    async def fake_cat_shards():
        return [{"index": "logs-app", "shard": "0", "prirep": "r", "state": "UNASSIGNED"}], None

    async def fake_allocation_explain():
        return {"unassigned_info": {"reason": "NODE_LEFT"}}, None

    monkeypatch.setattr(probe, "cat_shards", fake_cat_shards)
    monkeypatch.setattr(probe, "allocation_explain", fake_allocation_explain)
    result = await checks.check_unassigned_shards(is_real_problem=True)
    assert result["verdict"] == checks.FAIL
    assert result["detail"]["reason"] == "NODE_LEFT"


@pytest.mark.asyncio
async def test_thread_pool_rejections_warn_and_mentions_cumulative(monkeypatch):
    async def fake_stats():
        return {
            "nodes": {
                "n1": {"name": "node-1", "thread_pool": {"write": {"rejected": 5}, "search": {"rejected": 0}}},
            }
        }, None

    monkeypatch.setattr(probe, "nodes_thread_pool_stats", fake_stats)
    result = await checks.check_thread_pool_rejections()
    assert result["verdict"] == checks.WARN
    assert "累计" in result["summary"]


@pytest.mark.asyncio
async def test_thread_pool_rejections_all_zero_is_ok(monkeypatch):
    async def fake_stats():
        return {
            "nodes": {
                "n1": {"name": "node-1", "thread_pool": {"write": {"rejected": 0}, "search": {"rejected": 0}}},
            }
        }, None

    monkeypatch.setattr(probe, "nodes_thread_pool_stats", fake_stats)
    result = await checks.check_thread_pool_rejections()
    assert result["verdict"] == checks.OK


@pytest.mark.asyncio
async def test_read_only_block_is_fail(monkeypatch):
    async def fake_allocation():
        return [{"node": "n1", "disk.percent": "40"}], None

    async def fake_blocks():
        return {
            "logs-app-000001": {
                "settings": {"index": {"blocks": {"read_only_allow_delete": "true"}}}
            }
        }, None

    monkeypatch.setattr(probe, "cat_allocation", fake_allocation)
    monkeypatch.setattr(probe, "index_settings_blocks", fake_blocks)
    result = await checks.check_disk_watermark()
    assert result["verdict"] == checks.FAIL
    assert "logs-app-000001" in result["detail"]["read_only_indices"]


@pytest.mark.asyncio
async def test_disk_92_percent_is_warn(monkeypatch):
    async def fake_allocation():
        return [{"node": "n1", "disk.percent": "92"}], None

    async def fake_blocks():
        return {}, None

    monkeypatch.setattr(probe, "cat_allocation", fake_allocation)
    monkeypatch.setattr(probe, "index_settings_blocks", fake_blocks)
    result = await checks.check_disk_watermark()
    assert result["verdict"] == checks.WARN


@pytest.mark.asyncio
async def test_ilm_error_step_is_warn_with_reason(monkeypatch):
    async def fake_ilm():
        return {
            "indices": {
                "logs-app-000001": {"step": "ERROR", "step_info": {"reason": "policy references missing phase"}},
                "logs-app-000002": {"step": "hot"},
            }
        }, None

    monkeypatch.setattr(probe, "ilm_explain", fake_ilm)
    result = await checks.check_ilm_errors()
    assert result["verdict"] == checks.WARN
    assert result["detail"]["errored"][0]["reason"] == "policy references missing phase"


@pytest.mark.asyncio
async def test_ingest_freshness_thresholds_and_worst_wins(monkeypatch):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)

    async def fake_data_streams():
        return [{"name": "logs-a"}, {"name": "logs-b"}, {"name": "logs-c"}], None

    async def fake_last_doc_time(index):
        offsets = {"logs-a": 3, "logs-b": 8, "logs-c": 48}
        ts = now - timedelta(hours=offsets[index])
        return ts.isoformat().replace("+00:00", "Z"), None

    monkeypatch.setattr(probe, "data_streams", fake_data_streams)
    monkeypatch.setattr(probe, "last_doc_time", fake_last_doc_time)

    result = await checks.check_ingest_freshness(whitelist_patterns=[])
    assert result["verdict"] == checks.FAIL  # logs-c (48h) drags the whole check down
    by_name = {e["data_stream"]: e["verdict"] for e in result["detail"]["data_streams"]}
    assert by_name["logs-a"] == checks.OK
    assert by_name["logs-b"] == checks.WARN
    assert by_name["logs-c"] == checks.FAIL


@pytest.mark.asyncio
async def test_ingest_freshness_filters_by_whitelist(monkeypatch):
    async def fake_data_streams():
        return [{"name": "logs-app"}, {"name": ".security-alerts"}], None

    seen = []

    async def fake_last_doc_time(index):
        seen.append(index)
        return "2026-09-03T00:00:00Z", None

    monkeypatch.setattr(probe, "data_streams", fake_data_streams)
    monkeypatch.setattr(probe, "last_doc_time", fake_last_doc_time)

    result = await checks.check_ingest_freshness(whitelist_patterns=["logs-*"])
    names = [e["data_stream"] for e in result["detail"]["data_streams"]]
    assert names == ["logs-app"]
    assert seen == ["logs-app"]


@pytest.mark.asyncio
async def test_permission_error_degrades_to_unknown_not_raise(monkeypatch):
    async def fake_health():
        return None, "权限不足：需要 cluster monitor 权限"

    monkeypatch.setattr(probe, "cluster_health", fake_health)
    result = await checks.check_cluster_health()
    assert result["verdict"] == checks.UNKNOWN
    assert "权限不足" in result["summary"]


@pytest.mark.asyncio
async def test_run_all_survives_one_check_raising(monkeypatch):
    async def fake_health():
        return _health_dict("green")

    async def boom():
        raise RuntimeError("kaboom")

    monkeypatch.setattr(probe, "cluster_health", lambda: _ok(_health("green", n_nodes=3)))
    monkeypatch.setattr(checks, "check_thread_pool_rejections", boom)
    monkeypatch.setattr(checks, "check_disk_watermark", boom)
    monkeypatch.setattr(checks, "check_ilm_errors", boom)
    monkeypatch.setattr(checks, "check_ingest_freshness", boom)
    monkeypatch.setattr(checks, "check_time_baseline", boom)

    report = await checks.run_all()
    assert report["verdict"] in (checks.OK, checks.UNKNOWN)
    verdicts = {c["id"]: c["verdict"] for c in report["checks"]}
    assert verdicts["cluster_health"] == checks.OK
    assert sum(report["counts"].values()) == len(report["checks"])


async def _ok(data):
    return data, None


def _health_dict(status):
    return _health(status)
