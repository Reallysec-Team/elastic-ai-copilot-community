"""osquery 结果索引字段的运行时自检（卡点1 的解法）。

不同 Elastic / Fleet / Osquery Manager 版本下，三项字段名有差异，判定引擎取值
完全依赖它们。这里在部署后自主探测，不写死常量、不依赖人工跑探针贴回：

  优先级：env 覆盖 > mapping 自检 > 默认值(+ confident=False, 打 WARNING)

env 逃生口（客户字段诡异时）:
  RST_BASELINE_HOST_FIELD    主机标识字段
  RST_BASELINE_QUERY_FIELD   query 身份字段（关联键 = Pack query 名 == rule_id）
  RST_BASELINE_COL_PREFIX    结果列前缀（如 osquery.）

`probe_osquery_schema.py` 与本模块共用候选常量，是同一套启发式的诊断/校验版。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("rst.baseline.field_detect")

# 候选按优先级排序 —— 命中第一个存在的即采用。
QUERY_ID_CANDIDATES = (
    "osquery.pack_name", "osquery.name", "labels.query_name", "query",
    "osquery.action", "action", "data_stream.dataset", "event.dataset",
)
HOST_CANDIDATES = ("host.name", "host.hostname", "agent.id", "agent.name", "hostIdentifier")
RESULT_COL_PREFIXES = ("osquery.", "osquery_result.", "columns.")

# 自检失败时的兜底默认（Osquery Manager 常见形态）。confident=False 会打 WARNING。
DEFAULT_HOST = "host.name"
DEFAULT_QUERY = "osquery.pack_name"
DEFAULT_COL_PREFIX = "osquery."

_ENV_HOST = "RST_BASELINE_HOST_FIELD"
_ENV_QUERY = "RST_BASELINE_QUERY_FIELD"
_ENV_COL_PREFIX = "RST_BASELINE_COL_PREFIX"


@dataclass(frozen=True)
class FieldMap:
    host_field: str
    query_field: str
    col_prefix: str
    source: str          # "env" | "detected" | "default"
    confident: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "host_field": self.host_field,
            "query_field": self.query_field,
            "col_prefix": self.col_prefix,
            "source": self.source,
            "confident": self.confident,
        }


def _first_present(candidates: tuple[str, ...], fields: dict[str, str]) -> str | None:
    return next((c for c in candidates if c in fields), None)


def _detect_col_prefix(fields: dict[str, str]) -> str | None:
    for pfx in RESULT_COL_PREFIXES:
        if any(f.startswith(pfx) for f in fields):
            return pfx
    return None


def detect_from_fields(fields: dict[str, str]) -> FieldMap:
    """从扁平 mapping 字段集自检出 FieldMap（纯函数，便于测试）。"""
    env_host = os.environ.get(_ENV_HOST, "").strip() or None
    env_query = os.environ.get(_ENV_QUERY, "").strip() or None
    env_prefix = os.environ.get(_ENV_COL_PREFIX, "").strip() or None
    has_env = any((env_host, env_query, env_prefix))

    det_host = _first_present(HOST_CANDIDATES, fields)
    det_query = _first_present(QUERY_ID_CANDIDATES, fields)
    det_prefix = _detect_col_prefix(fields)

    host = env_host or det_host or DEFAULT_HOST
    query = env_query or det_query or DEFAULT_QUERY
    prefix = env_prefix or det_prefix or DEFAULT_COL_PREFIX

    # confident：三项都由 env 或自检得到（无一走默认）。
    host_ok = bool(env_host or det_host)
    query_ok = bool(env_query or det_query)
    prefix_ok = bool(env_prefix or det_prefix)
    confident = host_ok and query_ok and prefix_ok

    if has_env:
        source = "env"
    elif det_host or det_query or det_prefix:
        source = "detected"
    else:
        source = "default"

    if not confident:
        logger.warning(
            "baseline_field_detect_low_confidence",
            extra={"host_ok": host_ok, "query_ok": query_ok, "prefix_ok": prefix_ok,
                   "resolved": {"host": host, "query": query, "prefix": prefix}},
        )
    return FieldMap(host, query, prefix, source, confident)


def flatten_mapping(props: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """ES mapping properties 树 → {字段路径: 类型}。"""
    out: dict[str, str] = {}
    for name, spec in (props or {}).items():
        if not isinstance(spec, dict):
            continue
        path = f"{prefix}{name}"
        if "properties" in spec:
            out.update(flatten_mapping(spec["properties"], f"{path}."))
        else:
            out[path] = spec.get("type", "?")
        for sub in (spec.get("fields") or {}):
            out[f"{path}.{sub}"] = (spec["fields"][sub] or {}).get("type", "?")
    return out


def get_by_path(src: dict[str, Any], path: str) -> Any:
    """按点号路径读嵌套 _source 值，缺失返回 None。"""
    cur: Any = src
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def extract_columns(src: dict[str, Any], fm: FieldMap) -> dict[str, Any]:
    """从一份 _source 抽出结果列（col_prefix 下的键值），去掉前缀。

    col_prefix='osquery.' 且 src.osquery={username:..,uid:..} → {username:..,uid:..}
    """
    top = fm.col_prefix.rstrip(".")
    node = src.get(top)
    if isinstance(node, dict):
        return dict(node)
    # 前缀也可能以扁平点号键存在（osquery.username 直接是 key）
    out: dict[str, Any] = {}
    for k, v in (src or {}).items():
        if k.startswith(fm.col_prefix):
            out[k[len(fm.col_prefix):]] = v
    return out
