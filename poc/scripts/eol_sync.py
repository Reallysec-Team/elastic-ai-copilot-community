#!/usr/bin/env python3
"""同步 endoflife.date → 本地 eol-catalog 索引（离线 EOL 判定的数据源）。

判定期只读本地 catalog；本脚本是唯一出网点，手动/定时跑。
离线友好：客户内网无外网时，任一产品拉取失败 → 跳过该产品、保留旧缓存，
整体不报错退出（无外网属预期部署形态，不该 crash 巡检链路）。

用法（连到目标 ES 的环境变量同 gateway）:
    cd poc
    python -m scripts.eol_sync                          # 拉默认产品集
    python -m scripts.eol_sync --product centos,ubuntu  # 只拉指定产品
    python -m scripts.eol_sync --offline                # 不出网，仅报告现有缓存
    python -m scripts.eol_sync --base-url http://mirror.internal/eol  # 内网镜像

先决：已建索引 —— python -m scripts.baseline_setup_indices
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_POC = Path(__file__).resolve().parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.baseline import eol_catalog, eol_store  # noqa: E402
from backend.es_client import close_es  # noqa: E402

DEFAULT_BASE_URL = "https://endoflife.date/api"


def api_url(base_url: str, product: str) -> str:
    """endoflife 产品 JSON 端点。"""
    return f"{base_url.rstrip('/')}/{product}.json"


def parse_products(arg: str | None) -> list[str]:
    """--product 逗号分隔 → slug 列表；缺省用内置常见发行版集。"""
    if not arg:
        return list(eol_catalog.DEFAULT_PRODUCTS)
    return [p.strip() for p in arg.split(",") if p.strip()]


async def _fetch(client: Any, url: str, timeout: float) -> list[dict[str, Any]]:
    resp = await client.get(url, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


async def _run(products: list[str], base_url: str, offline: bool, timeout: float) -> int:
    synced_at = datetime.now(timezone.utc).isoformat()
    try:
        if offline:
            existing = await eol_store.count()
            print(f"[offline] 跳过出网同步，当前 eol-catalog 有 {existing} 条记录。")
            return 0

        import httpx  # 延迟导入：offline 路径不依赖 httpx

        docs: list[dict[str, Any]] = []
        ok, failed = [], []
        async with httpx.AsyncClient() as client:
            for product in products:
                try:
                    payload = await _fetch(client, api_url(base_url, product), timeout)
                    docs.extend(eol_catalog.transform_payload(product, payload, synced_at))
                    ok.append(product)
                except Exception as e:  # noqa: BLE001
                    # 单产品失败不阻断其余；无外网时全失败 → 保留旧缓存。
                    failed.append(product)
                    print(f"[warn] 拉取 {product} 失败（保留旧缓存）：{str(e)[:120]}")

        written = await eol_store.bulk_upsert(docs)
        total = await eol_store.count()
        print(f"完成：写入 {written} 条（{len(ok)} 个产品成功，{len(failed)} 个失败），"
              f"eol-catalog 现共 {total} 条。")
        if failed:
            print(f"失败产品：{', '.join(failed)}（内网无外网属预期，判定将复用现有缓存）")
        return 0
    finally:
        await close_es()


def main() -> None:
    ap = argparse.ArgumentParser(description="同步 endoflife.date → eol-catalog（离线友好）")
    ap.add_argument("--product", default=None, help="逗号分隔 slug（默认内置常见发行版集）")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL, help="endoflife API 基址（可指内网镜像）")
    ap.add_argument("--offline", action="store_true", help="不出网，仅报告现有缓存")
    ap.add_argument("--timeout", type=float, default=15.0, help="单请求超时秒")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(
        _run(parse_products(args.product), args.base_url, args.offline, args.timeout)))


if __name__ == "__main__":
    main()
