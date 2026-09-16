#!/usr/bin/env python3
"""本地测试用：合成 osquery 结果，灌入 logs-osquery_manager.result-demo。

客户环境有真实 Fleet+osquery 上报；本地没有，用本脚本顶替，验证判定闭环端到端。
关键：doc 的 osquery.pack_name = rule_id（演示「query 名 == rule_id」关联键），
主机字段 host.name，结果列挂 osquery.* —— 与真实 Osquery Manager 形态一致，
field_detect 能自检、query_builder 能命中。

只本地用，勿在客户环境跑（会污染结果索引）。

    cd poc
    ES_URL=http://localhost:9200 python -m scripts.baseline_seed_fake_osquery
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_POC = Path(__file__).resolve().parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.es_client import get_es, close_es  # noqa: E402

# 本地用非 `logs-` 名，避开 ES 内置 logs data-stream 模板（它禁止建普通索引）。
# 生产真实索引是 logs-osquery_manager.result-*（Fleet 建的 data stream，读路径不受影响）。
# 本地跑判定时用 RST_BASELINE_OSQUERY_INDEX=osquery-demo-* 指向这里即可。
INDEX = "osquery-demo-000001"

# 显式 mapping，还原真实 Osquery Manager 形态（host.name/osquery.* 都是 keyword，
# 否则本地自动映射成 text，term 查询会命不中）。
MAPPING: dict[str, Any] = {
    "mappings": {
        "properties": {
            "@timestamp": {"type": "date"},
            "action": {"type": "keyword"},
            "host": {"properties": {"name": {"type": "keyword"}}},
            "agent": {"properties": {"id": {"type": "keyword"}}},
        },
        "dynamic_templates": [
            {"osquery_keywords": {"path_match": "osquery.*", "mapping": {"type": "keyword"}}}
        ],
    }
}


def _doc(host: str, agent_id: str, rule_id: str, cols: dict[str, str], ts: str) -> dict[str, Any]:
    return {
        "@timestamp": ts,
        "action": "snapshot",
        "host": {"name": host},
        "agent": {"id": agent_id},
        "osquery": {"pack_name": rule_id, **cols},
    }


def _rows(ts: str) -> list[dict[str, Any]]:
    """故意造混合结果，覆盖各 operator，让判定出 pass + fail。

    未在此出现的规则 → 该主机无结果行 → expect_empty=pass / expect_nonempty=fail /
    equals=on_missing，演示"部分覆盖"下的判定行为。
    """
    return [
        # web01：一个明确 fail + 一个明确 pass
        _doc("web01", "agent-web01", "HB-NET-001", {"address": "0.0.0.0", "port": "23"}, ts),  # telnet 暴露 → expect_empty fail
        _doc("web01", "agent-web01", "HB-NET-003", {"current_value": "0"}, ts),                # ip_forward=0 → equals pass
        _doc("web01", "agent-web01", "HB-FW-001", {"chain": "INPUT", "policy": "DROP"}, ts),    # 有防火墙链 → expect_nonempty pass
        # db01：内核参数不合规 + SELinux 合规
        _doc("db01", "agent-db01", "HB-NET-003", {"current_value": "1"}, ts),                   # ip_forward=1 → equals fail
        _doc("db01", "agent-db01", "HB-MAC-001", {"current_value": "enforcing"}, ts),           # 注意：judge.field=current_value
        _doc("db01", "agent-db01", "HB-ACC-001", {"username": "backdoor", "uid": "0"}, ts),     # 非 root UID=0 → expect_empty fail
        # os_version → EOL 判定（HB-SYS-001, operator=eol）。判定需先跑 eol_sync 灌 eol-catalog：
        #   web01 CentOS 7（已 EOL）→ fail；db01 Ubuntu 22.04（受支持）→ pass。
        #   catalog 未同步时 → error（提示需同步），仍演示取值/字段命中。
        _doc("web01", "agent-web01", "HB-SYS-001",
             {"name": "CentOS Linux", "version": "7.9.2009", "platform": "rhel"}, ts),
        _doc("db01", "agent-db01", "HB-SYS-001",
             {"name": "Ubuntu", "version": "22.04.3 LTS", "platform": "ubuntu"}, ts),
    ]


async def _run() -> int:
    es = get_es()
    ts = datetime.now(timezone.utc).isoformat()
    try:
        if await es.indices.exists(index=INDEX):
            await es.indices.delete(index=INDEX)
        await es.indices.create(index=INDEX, body=MAPPING)
        ops: list[dict[str, Any]] = []
        for d in _rows(ts):
            ops.append({"index": {"_index": INDEX}})
            ops.append(d)
        await es.bulk(operations=ops, refresh=True)
    finally:
        await close_es()
    print(f"[ok] 灌入 {len(_rows(ts))} 条合成 osquery 结果到 {INDEX}（host: web01, db01）")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
