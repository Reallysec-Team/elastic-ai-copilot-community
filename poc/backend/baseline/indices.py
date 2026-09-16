"""baseline-rules / baseline-results / baseline-runs 三索引的 mapping 定义。

来源：桌面 baseline-index-mapping-and-dataflow.md，并按已定决策 #4 在 baseline-rules
增加结构化 remediation_command 字段（object, enabled:false，Phase1 留空、Phase3 LLM 填）。
dynamic:strict 防字段爆炸/脏数据。
"""
from __future__ import annotations

from typing import Any

RULES_MAPPING: dict[str, Any] = {
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "rule_id": {"type": "keyword"},
            "title": {"type": "text", "fields": {"kw": {"type": "keyword"}}},
            "category": {"type": "keyword"},
            "platform": {"type": "keyword"},
            "standard_refs": {"type": "keyword"},
            "severity": {"type": "keyword"},
            "depends_on": {"type": "keyword", "null_value": "none"},
            "collect": {
                "properties": {
                    "type": {"type": "keyword"},
                    "query": {"type": "text", "index": False},
                    "query_name": {"type": "keyword"},  # osquery Pack query 名（关联键，默认 rule_id）
                }
            },
            "judge": {
                "properties": {
                    "operator": {"type": "keyword"},
                    "field": {"type": "keyword"},
                    "expected": {"type": "keyword"},
                    "on_missing": {"type": "keyword"},
                }
            },
            "remediation_template": {"type": "text", "index": False},
            # 决策 #4：结构化整改命令，Phase1 空、Phase3 LLM 填。
            # object + enabled:false → 存不索引，形如
            #   {"commands": ["..."], "platform": "linux", "requires_confirm": true}
            "remediation_command": {"type": "object", "enabled": False},
            "enabled": {"type": "boolean"},
            # "pack" = 从 osquery Pack 导入的内置规则；"custom" = 网页里自建/编辑的规则。
            "source": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        },
    }
}

RESULTS_MAPPING: dict[str, Any] = {
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "run_id": {"type": "keyword"},
            "rule_id": {"type": "keyword"},
            "title": {"type": "keyword"},
            "category": {"type": "keyword"},
            "severity": {"type": "keyword"},
            "standard_refs": {"type": "keyword"},
            "host": {"type": "keyword"},
            "agent_id": {"type": "keyword"},
            "verdict": {"type": "keyword"},
            "actual": {"type": "keyword", "ignore_above": 1024},
            "expected": {"type": "keyword"},
            "evidence": {"type": "text", "index": False},
            "remediation": {"type": "text", "index": False},
            "checked_at": {"type": "date"},
        },
    }
}

RUNS_MAPPING: dict[str, Any] = {
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "run_id": {"type": "keyword"},
            "trigger": {"type": "keyword"},
            "rule_count": {"type": "integer"},
            "host_count": {"type": "integer"},
            "pass": {"type": "integer"},
            "fail": {"type": "integer"},
            "error": {"type": "integer"},
            "manual_review": {"type": "integer"},
            "score": {"type": "float"},
            "started_at": {"type": "date"},
            "finished_at": {"type": "date"},
        },
    }
}


# eol-catalog：离线 EOL 判定的本地数据源（endoflife.date 快照）。dynamic:strict。
# eol/release_date 可空 → 写入前剔除 None 字段（date 不吃 null），见 eol_store.bulk_upsert。
EOL_CATALOG_MAPPING: dict[str, Any] = {
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "product": {"type": "keyword"},      # endoflife slug: centos/rhel/ubuntu...
            "cycle": {"type": "keyword"},         # "7" / "8" / "22.04"
            "eol": {"type": "date"},              # 解析出的 EOL 日期（bool 值时缺省）
            "eol_raw": {"type": "keyword"},       # 原始值："2024-06-30" | "true" | "false"
            "release_date": {"type": "date"},
            "latest": {"type": "keyword"},
            "synced_at": {"type": "date"},        # 本次同步时间（离线判空/审计）
            "source": {"type": "keyword"},        # "endoflife.date"
        },
    }
}


def index_specs(rules_index: str, results_index: str, runs_index: str,
                eol_index: str = "eol-catalog") -> list[tuple[str, dict]]:
    return [
        (rules_index, RULES_MAPPING),
        (results_index, RESULTS_MAPPING),
        (runs_index, RUNS_MAPPING),
        (eol_index, EOL_CATALOG_MAPPING),
    ]
