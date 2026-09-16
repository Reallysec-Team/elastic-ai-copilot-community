"""osquery 结果索引字段运行时自检（TDD）。

判定引擎不写死字段常量，而是从真实 mapping 自检出:
  - query 身份字段（把结果行对应到规则；关联键 = Pack query 名 == rule_id）
  - 主机标识字段（host.name / agent.id ...）
  - 结果列前缀（osquery.* ...）

优先级: env 覆盖 > mapping 自检 > 默认值(+标记 low confidence)。
"""
from __future__ import annotations

import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.baseline import field_detect  # noqa: E402


# 典型 Osquery Manager 结果索引扁平字段集
_TYPICAL = {
    "@timestamp": "date",
    "host.name": "keyword",
    "host.hostname": "keyword",
    "agent.id": "keyword",
    "action": "keyword",
    "osquery.pack_name": "keyword",
    "osquery.username": "keyword",
    "osquery.uid": "keyword",
    "osquery.current_value": "keyword",
}


def test_detect_from_typical_mapping():
    fm = field_detect.detect_from_fields(_TYPICAL)
    assert fm.host_field == "host.name"
    assert fm.query_field == "osquery.pack_name"
    assert fm.col_prefix == "osquery."
    assert fm.confident is True
    assert fm.source == "detected"


def test_detect_falls_back_to_agent_id_when_no_host_name():
    fields = {"agent.id": "keyword", "osquery.pack_name": "keyword", "osquery.x": "keyword"}
    fm = field_detect.detect_from_fields(fields)
    assert fm.host_field == "agent.id"


def test_detect_empty_mapping_uses_defaults_low_confidence():
    fm = field_detect.detect_from_fields({})
    assert fm.confident is False
    assert fm.source == "default"
    # 默认值必须是合法非空，判定引擎不至于崩
    assert fm.host_field and fm.query_field and fm.col_prefix


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("RST_BASELINE_HOST_FIELD", "custom.host")
    monkeypatch.setenv("RST_BASELINE_QUERY_FIELD", "custom.qname")
    monkeypatch.setenv("RST_BASELINE_COL_PREFIX", "cols.")
    fm = field_detect.detect_from_fields(_TYPICAL)
    assert fm.host_field == "custom.host"
    assert fm.query_field == "custom.qname"
    assert fm.col_prefix == "cols."
    assert fm.source == "env"
    assert fm.confident is True


def test_partial_env_override_mixes_with_detection(monkeypatch):
    # 只覆盖 host，其余仍自检
    monkeypatch.setenv("RST_BASELINE_HOST_FIELD", "custom.host")
    fm = field_detect.detect_from_fields(_TYPICAL)
    assert fm.host_field == "custom.host"
    assert fm.query_field == "osquery.pack_name"  # 仍自检
    assert fm.source == "env"  # 有任一 env 覆盖即标记 env


def test_extract_columns_strips_prefix():
    fm = field_detect.FieldMap(host_field="host.name", query_field="osquery.pack_name",
                               col_prefix="osquery.", source="detected", confident=True)
    src = {
        "host": {"name": "web01"},
        "osquery": {"pack_name": "HB-ACC-001", "username": "root", "uid": "0"},
        "action": "snapshot",
    }
    cols = field_detect.extract_columns(src, fm)
    assert cols == {"pack_name": "HB-ACC-001", "username": "root", "uid": "0"}


def test_get_by_path_reads_nested():
    src = {"host": {"name": "web01"}, "agent": {"id": "a-1"}}
    assert field_detect.get_by_path(src, "host.name") == "web01"
    assert field_detect.get_by_path(src, "agent.id") == "a-1"
    assert field_detect.get_by_path(src, "missing.x") is None
