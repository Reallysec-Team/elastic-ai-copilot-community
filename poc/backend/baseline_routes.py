"""安全基线巡检 API（Task A）。

导出 FastAPI APIRouter，在 main.py 经 app.include_router 挂载。

  POST /api/baseline/run        触发一轮判定（body 可选 {"hosts":[...]}），返回批次汇总
  GET  /api/baseline/results    查判定结果（run_id / host / verdict 过滤）
  GET  /api/baseline/summary    最近一轮批次汇总（评分卡）
  GET  /api/baseline/hosts      上报过 osquery 的主机集合
  GET  /api/baseline/field-map  当前解析出的 osquery 字段映射（运维可核自检结果）

判定纯读 osquery 结果索引 + 写 baseline-* 索引，不调 LLM（Task A）。
认证由 /api/* 的 SharedSecretMiddleware 覆盖。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from .baseline import engine, result_reader, store
from .baseline.rule_input import validate_rule_payload
from .es_client import es_api_error
from .api_errors import ApiError
from .auth import require_admin

logger = logging.getLogger("rst.baseline.api")

router = APIRouter(tags=["baseline"])


class BaselineRunRequest(BaseModel):
    hosts: list[str] | None = None  # 省略 = 自动枚举全部上报主机


def _new_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{ts}-{uuid.uuid4().hex[:8]}"


@router.post("/api/baseline/run")
async def baseline_run(req: BaselineRunRequest) -> dict[str, Any]:
    run_id = _new_run_id()
    try:
        summary = await engine.run_baseline(run_id, hosts=req.hosts)
    except Exception as e:  # noqa: BLE001
        logger.warning("baseline_run_failed", extra={"run_id": run_id, "error": str(e)})
        raise es_api_error(e)
    return summary


@router.get("/api/baseline/results")
async def baseline_results(run_id: str | None = None, host: str | None = None,
                           verdict: str | None = None, size: int = 1000) -> dict[str, Any]:
    try:
        items = await store.list_results(run_id=run_id, host=host, verdict=verdict, size=size)
    except Exception as e:  # noqa: BLE001
        raise es_api_error(e)
    return {"count": len(items), "results": items}


@router.get("/api/baseline/summary")
async def baseline_summary() -> dict[str, Any]:
    try:
        run = await store.latest_run()
    except Exception as e:  # noqa: BLE001
        raise es_api_error(e)
    return {"run": run}


@router.get("/api/baseline/hosts")
async def baseline_hosts() -> dict[str, Any]:
    try:
        hosts = await result_reader.list_hosts()
    except Exception as e:  # noqa: BLE001
        raise es_api_error(e)
    return {"count": len(hosts), "hosts": hosts}


@router.get("/api/baseline/field-map")
async def baseline_field_map() -> dict[str, Any]:
    """暴露运行时自检出的 osquery 字段映射，运维可核对（source/confident）。"""
    fm = await result_reader.get_field_map()
    return fm.as_dict()


@router.get("/api/baseline/rules")
async def baseline_list_rules(platform: str | None = None) -> dict[str, Any]:
    """列出规则库全部规则（含 disabled），供规则浏览与编辑。"""
    try:
        rules = await store.list_all_rules(platform=platform)
    except Exception as e:  # noqa: BLE001
        raise es_api_error(e)
    return {"count": len(rules), "rules": rules}


@router.get("/api/baseline/runs")
async def baseline_list_runs(size: int = 50) -> dict[str, Any]:
    """历史巡检轮次（最近优先），供历史列表 + 下钻。"""
    try:
        runs = await store.list_runs(size=size)
    except Exception as e:  # noqa: BLE001
        raise es_api_error(e)
    return {"count": len(runs), "runs": runs}


@router.post("/api/baseline/rules")
async def baseline_upsert_rule(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    """新建 / 更新一条规则（文档 id = rule_id，幂等）。引擎下一轮巡检即生效。

    这会写入驱动安全判定的规则，故先严格校验（operator / 必填字段 / rule_id 形态）。

    要管理员：`collect.query` 是会被导出成 osquery Pack、下发到全部端点上执行的
    SQL（baseline/pack.py），校验只管形状不管内容。中间件那道闸按方法判，挡的是
    viewer，analyst 的 POST 是放行的 —— 谁能写下发到端点的语句，得路由自己说。
    """
    require_admin(request)
    try:
        rule = validate_rule_payload(payload)
    except ApiError:
        raise
    except ValueError as e:
        raise ApiError("invalid_request", reason=e)
    try:
        await store.upsert_rule(rule)
    except Exception as e:  # noqa: BLE001
        raise es_api_error(e)
    return {"ok": True, "rule_id": rule.rule_id}


@router.delete("/api/baseline/rules/{rule_id}")
async def baseline_delete_rule(rule_id: str, request: Request) -> dict[str, Any]:
    """删除一条规则。写路径同 upsert，要管理员。"""
    require_admin(request)
    try:
        ok = await store.delete_rule(rule_id)
    except Exception as e:  # noqa: BLE001
        raise es_api_error(e)
    if not ok:
        raise ApiError("baseline_rule_not_found", 404, rule_id=rule_id)
    return {"ok": True, "rule_id": rule_id}
