import os
from typing import Any

from elasticsearch import (
    AsyncElasticsearch,
    AuthenticationException,
    AuthorizationException,
    ConnectionError as ESConnectionError,
    ConnectionTimeout,
    NotFoundError,
)

from .api_errors import ApiError

_es: AsyncElasticsearch | None = None

# 异常类型 → (错误码, HTTP 状态)。文案在 api_errors.MESSAGES 里，中英各一份。
_ES_ERROR_CODES: list[tuple[type, str, int]] = [
    (ConnectionTimeout, "es_timeout", 504),
    (ESConnectionError, "es_unreachable", 503),
    (AuthenticationException, "es_auth_failed", 502),
    (AuthorizationException, "es_forbidden", 502),
    (NotFoundError, "es_index_not_found", 404),
]


def es_api_error(e: Exception) -> ApiError:
    """把 ES 异常翻成带错误码的 ApiError。

    `friendly_es_error` 只给 (状态, 中文文案)，路由拿它拼裸 HTTPException —— 这条
    链路上的错误因此没有码，英文界面翻不了。两者说的是同一件事，文案也在同一张表里。
    """
    for exc_type, code, status in _ES_ERROR_CODES:
        if isinstance(e, exc_type):
            return ApiError(code, status)
    return ApiError("es_request_failed", 502, reason=str(e)[:200])


def friendly_es_error(e: Exception) -> tuple[int, str]:
    """Map a raw Elasticsearch exception to (http_status, user-facing message).

    Analysts used to see opaque 500s when ES was down, slow, or an index was
    missing — with no hint whether to retry, fix the query, or call ops. This
    classifies the common cases into something actionable.
    """
    if isinstance(e, ConnectionTimeout):
        return 504, "Elasticsearch 查询超时。集群可能负载较高，可稍后重试或调小时间范围 / 结果条数。"
    if isinstance(e, ESConnectionError):
        return 503, "无法连接 Elasticsearch。请检查 ES 是否在线、网络是否可达（ES_URL 配置）。"
    if isinstance(e, AuthenticationException):
        return 502, "Elasticsearch 认证失败。请检查 ES_USER / ES_PASSWORD 配置。"
    if isinstance(e, AuthorizationException):
        return 502, "当前 ES 账号无权访问该索引。请检查 ES 角色权限。"
    if isinstance(e, NotFoundError):
        return 404, "索引不存在。请确认索引名 / 别名是否正确，或它是否已被滚动删除。"
    return 502, f"Elasticsearch 请求失败：{str(e)[:200]}"


def _verify_certs() -> bool:
    # 默认校验证书。之前默认 False，意味着 https 的 ES 默认裸奔 —— 谁都能中间人，
    # 而这条链路上跑的是客户的告警和日志。自签名 / 内部 CA 的集群配
    # RST_ES_CA_CERT=/path/to/ca.pem（下面会顺带把 verify 打开）；确实要关就显式
    # 设 RST_ES_VERIFY_CERTS=false。
    return os.environ.get("RST_ES_VERIFY_CERTS", "").strip().lower() not in ("0", "false", "no")


def _env_float(name: str, default: float) -> float:
    try:
        v = float(os.environ.get(name, "").strip())
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name, "").strip())
        return v if v >= 0 else default
    except (TypeError, ValueError):
        return default


def build_client(
    url: str | None = None,
    user: str | None = None,
    password: str | None = None,
    verify_certs: bool | None = None,
    ca_cert: str | None = None,
) -> AsyncElasticsearch:
    """Build an ES client. Every argument defaults to its environment variable.

    Split out of `get_es` so the settings UI can dial a *candidate* cluster —
    ping it, check write permission — without touching the live singleton. A
    connection the admin has not confirmed yet must never become the connection
    the gateway uses.
    """
    # `or` rather than a dict default: a fresh install ships ES_URL= (blank) in
    # .env, and an empty string is set-but-useless — it reaches the transport as
    # a hostless URL and raises a parse error instead of a connection error.
    hosts = [(url if url is not None else os.environ.get("ES_URL", "")).strip()
             or "http://localhost:9200"]
    user = user if user is not None else os.environ.get("ES_USER")
    password = password if password is not None else os.environ.get("ES_PASSWORD")
    verify = _verify_certs() if verify_certs is None else verify_certs
    ca_cert = ca_cert if ca_cert is not None else os.environ.get("RST_ES_CA_CERT", "")

    kwargs: dict[str, Any] = {"hosts": hosts, "verify_certs": verify}
    # Resilience knobs — a slow / flapping customer ES used to hang every
    # request indefinitely and surface as an opaque 500. These give a bounded
    # wait, transparent retries on timeout / connection errors, and a tunable
    # pool for larger deployments. All optional with safe defaults.
    kwargs["request_timeout"] = _env_float("RST_ES_TIMEOUT_S", 30.0)
    kwargs["max_retries"] = _env_int("RST_ES_MAX_RETRIES", 2)
    kwargs["retry_on_timeout"] = True
    pool_size = _env_int("RST_ES_MAX_POOL_SIZE", 0)
    if pool_size > 0:
        kwargs["connections_per_node"] = pool_size
    if ca_cert.strip():
        # A custom CA implies the operator wants verification on.
        kwargs["ca_certs"] = ca_cert.strip()
        kwargs["verify_certs"] = True
    if user and password:
        kwargs["basic_auth"] = (user, password)
    return AsyncElasticsearch(**kwargs)


def get_es() -> AsyncElasticsearch:
    """The shared ES client. 二十多个模块 import 它，是事实上的公共接口。

    客户端是模块级单例，绑在第一次调用它的那个事件循环上 —— 所以自己开
    `asyncio.run(...)` 的测试要在 fixture 里把 `es_client._es` 复位，否则
    后面用 TestClient 的用例会拿到一个循环已经关掉的客户端。
    """
    global _es
    if _es is None:
        _es = build_client()
    return _es


def reset_client() -> AsyncElasticsearch | None:
    """Drop the singleton and hand back the old client for the caller to close.

    Used when the admin re-points the gateway at a different cluster from the
    settings UI: the next request must dial the new host, and the old client's
    sockets have to be closed by someone who can await.
    """
    global _es
    old, _es = _es, None
    return old


async def close_es() -> None:
    global _es
    if _es is not None:
        await _es.close()
        _es = None


async def ping() -> bool:
    """Liveness check for Elasticsearch — used by /readyz."""
    return await get_es().ping()


async def get_mapping(index: str) -> dict[str, Any]:
    es = get_es()
    resp = await es.indices.get_mapping(index=index)
    return resp.body


async def execute_search(index: str, dsl: dict[str, Any]) -> dict[str, Any]:
    es = get_es()
    resp = await es.search(index=index, body=dsl)
    return resp.body
