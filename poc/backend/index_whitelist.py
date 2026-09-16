"""Index whitelist enforcement, plus the hard deny for product-owned indices.

If `RST_INDEX_WHITELIST` is set (comma-separated patterns, glob-style), any
endpoint that takes an `index` parameter rejects requests for indices outside
the list with HTTP 403.

Examples:
  RST_INDEX_WHITELIST=logs-*,metrics-*,kibana_sample_*
  RST_INDEX_WHITELIST=     (unset/empty → no restriction; dev default)

Customer admin should always set this in production. Without it, any user could
ask the gateway to query e.g. `.security-*` and the gateway would dutifully forward.
"""

import logging
import os
from fnmatch import fnmatch

from . import owned_indices

logger = logging.getLogger("rst.whitelist")


class IndexWhitelist:
    def __init__(self, patterns: list[str]):
        self._patterns = [p.strip() for p in patterns if p.strip()]

    def is_allowed(self, index: str) -> bool:
        if not self._patterns:
            return True
        # ES treats `index` as a comma-separated multi-index list, and glob
        # patterns like `logs-*` would otherwise match commas — letting a caller
        # smuggle a blocked index in via `logs-app,.security-7`. Require EVERY
        # segment to match the whitelist independently.
        segments = [s.strip() for s in index.split(",")]
        segments = [s for s in segments if s]
        if not segments:
            return False
        for seg in segments:
            # Strip ES include/exclude prefixes so `-foo`/`+foo` are checked by name.
            name = seg.lstrip("+-")
            if not any(fnmatch(name, p) for p in self._patterns):
                return False
        return True

    def patterns(self) -> list[str]:
        return list(self._patterns)

    def is_active(self) -> bool:
        return bool(self._patterns)


def blocked_owned(index: str) -> str | None:
    """产品自有索引的名字，如果这次请求会碰到它；否则 None。

    这道闸**和白名单无关**，因为白名单为空时 `is_allowed` 恒真，而
    `RST_INDEX_WHITELIST` 的默认值就是空（docker-compose.prod.yml）。也就是说
    在默认部署上，任何登录账号都能把 `/api/execute` 指向
    `.rst_copilot_userstate`（别人的查询历史和偏好）、审计索引、或者通知配置
    文档（里面存着明文的 webhook_url）。这条路同时也是 prompt injection 的落点：
    agentic 循环每次 tool call 都过白名单，白名单为空时那个检查同样恒真。

    只挡产品自己写的那批索引，不挡所有点号开头的索引 —— 客户的
    `.alerts-security.alerts-default` 正是这个产品要读的东西，那是数据源不是
    内部存储（见 owned_indices 的模块注释）。

    `fnmatch(name, seg)` 的方向是「用户给的模式去匹配自有索引名」，所以
    `*` 和 `.rst_copilot_*` 这种通配也会被挡住，不只是精确名字。
    """
    owned = owned_indices.owned_index_names()
    if not owned:
        return None
    # ES 把 index 当成逗号分隔的多索引列表；`+` / `-` 是它的包含排除前缀。
    for seg in (s.strip() for s in index.split(",")):
        if not seg:
            continue
        seg = seg.lstrip("+-")
        for name in owned:
            if seg == name or fnmatch(name, seg):
                return name
    return None


def from_env() -> IndexWhitelist:
    raw = os.environ.get("RST_INDEX_WHITELIST", "").strip()
    if not raw:
        return IndexWhitelist([])
    return IndexWhitelist(raw.split(","))


_singleton: IndexWhitelist | None = None


def get() -> IndexWhitelist:
    global _singleton
    if _singleton is None:
        _singleton = from_env()
        if _singleton.is_active():
            logger.info(
                "index_whitelist_active",
                extra={"patterns": _singleton.patterns()},
            )
        else:
            logger.warning(
                "index_whitelist_unset — RST_INDEX_WHITELIST is empty. "
                "Gateway accepts queries against any index. OK for dev; set this in production."
            )
    return _singleton
