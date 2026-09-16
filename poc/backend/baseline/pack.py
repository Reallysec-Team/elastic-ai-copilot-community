"""从规则库导出 Fleet 可导入的 osquery Pack（方案 C）。

规则库与 osquery Pack 同源（collect.query 就是 osquery SQL）。由产品统一产出 Pack，
query 名 = query_name（默认 rule_id），客户一次性导入 Fleet Osquery Manager 即可，
「query 名 == rule_id」的关联对齐 by construction，无需客户手工对齐、不会漂移。

输出为标准 osquery pack 格式（Elastic Osquery Manager 可直接导入）:
    {"queries": {"<query_name>": {"query", "interval", "snapshot", "platform", "description"}}}

注：field_detect 负责「哪个 ES 字段承载 query 名」；本模块负责「query 名 = rule_id」。
两者配合闭合关联键。
"""
from __future__ import annotations

from typing import Any

from .schema import Rule

DEFAULT_INTERVAL = 3600  # 秒；与客户期望巡检频率对齐（判定轮询间隔应 >= 此值）


def build_pack(rules: list[dict[str, Any]], interval: int = DEFAULT_INTERVAL,
               pack_name: str = "rst-baseline-phase1") -> dict[str, Any]:
    """把规则字典列表转成 osquery pack。跳过无 SQL 的规则（如纯 manual_review）。

    确定性：同输入同输出。基线要当前状态，故 snapshot=true（非差分）。
    """
    queries: dict[str, Any] = {}
    for rd in rules:
        r = Rule.from_dict(rd)
        if not r.collect_query.strip():
            continue
        queries[r.query_name] = {
            "query": r.collect_query,
            "interval": interval,
            "snapshot": True,
            "platform": r.platform or "linux",
            "description": r.title or r.rule_id,
        }
    return {"pack_name": pack_name, "queries": queries}
