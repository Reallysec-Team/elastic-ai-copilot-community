"""哪些路由会花掉一次 LLM 调用 —— 在路由那儿声明，不再靠两张手工枚举表。

（这个文件里没有路由。原来叫 `llm_routes.py`，跟 `llm_router.py`（多厂商故障
切换）只差一个字母，而且名字说的是它没有的东西 —— 它是一张「谁花钱」的登记表，
额度闸和限流桶都从这里读。）

以前这件事分散在两个地方：`license_gate._GATED_GENERATIVE`（未激活时扣额度）和
`rate_limit._BUCKET_SPEC`（限流桶）。两张表都要人记得同步，结果就是
`/api/investigate-alert/stream`、`/api/explain-result`、`/api/reports/generate`、
`/api/kb/search` 四条既不扣额度也没有桶 —— 加一条会调 LLM 的路由时，忘记登记
不会让任何东西变红。

现在改成在路由定义处标注：

    llm_post = llm_cost.marker(app)

    @llm_post("/api/execute", rpm_env="RST_RATELIMIT_EXECUTE", rpm=30.0)
    async def execute(...): ...

`marker()` 对 FastAPI 的 `app` 和 `APIRouter` 一样用，注册完就转交给
`target.post(path, **kw)`，路由行为一个字没变。两个消费方改成惰性读这里，
`tests/test_llm_route_marks.py` 盯着「登记的路径都真实存在」和
「会调 LLM 的路由都登记了」。
"""

from __future__ import annotations

from typing import Any, Callable

# path → {"quota": bool, "rpm": float | None, "rpm_env": str | None}
_REGISTRY: dict[str, dict[str, Any]] = {}


def mark(
    path: str,
    *,
    quota: bool = True,
    rpm: float | None = None,
    rpm_env: str | None = None,
) -> None:
    """登记一条会调 LLM 的路由。

    quota   未激活试用额度是否扣在这条上（生成类都该扣）。
    rpm     默认限流（次/分）。None = 不限流，只有确定廉价的路由才这么写。
    rpm_env 覆盖这个默认值的环境变量名。
    """
    _REGISTRY[path] = {"quota": quota, "rpm": rpm, "rpm_env": rpm_env}


def marker(target: Any) -> Callable[..., Any]:
    """返回一个替代 `target.post` 的装饰器工厂，顺手登记这条路由。"""

    def llm_post(
        path: str,
        *,
        quota: bool = True,
        rpm: float | None = None,
        rpm_env: str | None = None,
        **kw: Any,
    ) -> Callable[..., Any]:
        mark(path, quota=quota, rpm=rpm, rpm_env=rpm_env)
        return target.post(path, **kw)

    return llm_post


def generative() -> frozenset[str]:
    """扣额度的路由（license_gate 用）。"""
    return frozenset(p for p, spec in _REGISTRY.items() if spec["quota"])


def rate_limits() -> dict[str, tuple[str, float]]:
    """path → (env var, 默认 req/min)（rate_limit 用）。"""
    return {
        p: (spec["rpm_env"] or "", float(spec["rpm"]))
        for p, spec in _REGISTRY.items()
        if spec["rpm"] is not None
    }


def registered() -> dict[str, dict[str, Any]]:
    return dict(_REGISTRY)
