"""基线巡检定时轮询触发器（卡点2 已定：轮询，不用 ES Watcher）。

进程内 asyncio 循环（同 heartbeat.py / report_scheduler.py 形态）。与客户侧 osquery
Pack 的 interval 对齐即可（如每天/每小时），每次跑一轮全量判定，写新 run。

OFF by default。启用:
  RST_BASELINE_INTERVAL_SECONDS   轮询间隔秒（>=300 生效；未设/过小 = 关）
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

from . import engine

logger = logging.getLogger("rst.baseline.scheduler")

_task: asyncio.Task | None = None
MIN_INTERVAL = 300  # 5 分钟下限，防误配打爆 ES


def _interval() -> int:
    try:
        v = int(os.environ.get("RST_BASELINE_INTERVAL_SECONDS", "0"))
    except (TypeError, ValueError):
        return 0
    return v if v >= MIN_INTERVAL else 0


def _run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{ts}-{uuid.uuid4().hex[:8]}"


async def _loop(interval: int) -> None:
    logger.info("baseline_scheduler_started", extra={"interval_s": interval})
    while True:
        try:
            summary = await engine.run_baseline(_run_id(), hosts=None)
            logger.info("baseline_scheduled_run", extra={
                "run_id": summary["run_id"], "score": summary["score"],
                "pass": summary["pass"], "fail": summary["fail"]})
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001
            logger.exception("baseline_scheduler_run_error")
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break


def start() -> None:
    """启用则起循环，否则 no-op。"""
    global _task
    interval = _interval()
    if interval <= 0:
        return
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(interval))


async def stop() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
