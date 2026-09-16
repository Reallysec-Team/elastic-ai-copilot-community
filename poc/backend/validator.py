import os
from typing import Any

_FORBIDDEN_KEYS = {
    "script",
    "scripted_metric",
    "update",
    "delete",
    "_delete_by_query",
    "_update_by_query",
}


# Cap total node count, not just nesting depth: a shallow DSL with a
# multi-million-element `terms`/`should` array passes a depth-only check yet
# still forces ES to build a huge query — a cost/DoS vector. 200k nodes is far
# above any legitimate generated query but bounds the worst case.
_MAX_NODES = 200_000

# `/api/execute` 转发用户给的 DSL 原样打向 ES。节点数上限拦得住"一个巨大的
# 查询体"，拦不住"一个很小但很贵的查询"：`size: 10000` 加两层高基数 terms
# 聚合，请求体只有几百字节，ES 那边却要建十万个桶。
#
# 最坏情况本来就被 ES 自己的 `max_result_window`(10000) 和
# `search.max_buckets`(65536) 兜着 —— 超了会 400，网关翻成 502。所以这不是
# 无界，但在 ES 默认上限之内仍然构造得出很贵的查询，而网关这一层此前完全没
# 设防。这两个上限就是那道防线，都可以按部署调。
_DEFAULT_MAX_SIZE = 1000
_DEFAULT_MAX_BUCKETS = 10_000

# 会产生桶的聚合类型 → 它身上表示"要几个桶"的那个键。列的是本产品的 NL→DSL
# 真会生成的那几种；没列到的（date_histogram 之类按区间自己定数量的）由
# ES 的 search.max_buckets 兜。
_BUCKET_SIZE_KEYS = {
    "terms": "size",
    "significant_terms": "size",
    "multi_terms": "size",
    "rare_terms": "size",
}
_AGG_KEYS = ("aggs", "aggregations")


def _env_int(name: str, default: int) -> int:
    """按调用时读，不在 import 期定死 —— 部署改了环境变量不用重开进程，测试也
    不必去 monkeypatch 模块级常量。"""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
    except ValueError:
        return default
    return v if v > 0 else default


def validate_dsl(dsl: dict[str, Any]) -> None:
    if not isinstance(dsl, dict):
        raise ValueError("DSL must be a JSON object.")
    _scan(dsl, depth=0, counter=[0])
    _check_cost(dsl)


def _check_cost(dsl: dict[str, Any]) -> None:
    """命中数和聚合桶数的上限。"""
    max_size = _env_int("RST_MAX_QUERY_SIZE", _DEFAULT_MAX_SIZE)
    max_buckets = _env_int("RST_MAX_AGG_BUCKETS", _DEFAULT_MAX_BUCKETS)

    # ES 的 max_result_window 管的是 from+size，不是 size 单独。深翻页
    # （from: 9990, size: 10）跟一次取一万同样贵。
    size = _as_int(dsl.get("size"))
    # `from` 缺省就是 0；写成 `frm is not None` 那种守卫会让不带 from 的
    # `size: 10000` 整条溜过去 —— 而那才是最常见的那一种。
    frm = _as_int(dsl.get("from")) or 0
    if size is not None and size + frm > max_size:
        raise ValueError(
            f"DSL too expensive: from+size={size + frm} exceeds the {max_size} cap "
            "(RST_MAX_QUERY_SIZE)."
        )

    buckets = _max_buckets(dsl)
    if buckets > max_buckets:
        raise ValueError(
            f"DSL too expensive: the aggregations can produce up to {buckets} buckets, "
            f"over the {max_buckets} cap (RST_MAX_AGG_BUCKETS)."
        )


def _as_int(v: Any) -> int | None:
    """`size` 可能是 int，也可能是模型写出来的字符串 "10000"。不是数就当没写。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return int(v.strip())
        except ValueError:
            return None
    return None


def _max_buckets(node: Any) -> int:
    """这棵聚合树最多能产出多少个桶。

    嵌套聚合是**相乘**的：`terms(size=1000)` 里再套一个 `terms(size=1000)` 就是
    一百万个桶，而这两个数字单看都不吓人。所以要沿着每条分支连乘，取最大的
    那条。同级的多个聚合是相加，不是相乘。
    """
    if not isinstance(node, dict):
        return 0
    total = 0
    for aggs_key in _AGG_KEYS:
        aggs = node.get(aggs_key)
        if not isinstance(aggs, dict):
            continue
        for body in aggs.values():
            if not isinstance(body, dict):
                continue
            own = 1
            for agg_type, size_key in _BUCKET_SIZE_KEYS.items():
                spec = body.get(agg_type)
                if isinstance(spec, dict):
                    n = _as_int(spec.get(size_key))
                    # terms 不写 size 时 ES 默认 10 —— 按默认算，别当成 1。
                    own = max(own, n if n is not None else 10)
            nested = _max_buckets(body)
            total += own * max(1, nested) if nested else own
    return total


def apply_default_sort(dsl: dict[str, Any]) -> dict[str, Any]:
    """Return `dsl` with a newest-first sort when it does not already have one.

    ES leaves hit order undefined for an unsorted search, and against a data
    stream the shard merge falls out in backing-index order — oldest generation
    first. So a `size: 10` query over `logs-system.security-default` spanning
    months returns ten of the *oldest* documents, which reads on screen as
    "ingestion stopped in May". Every hand-written query in this codebase
    already sorts; only the LLM-authored ones did not.

    `unmapped_type` keeps a multi-index target from 400-ing when one of the
    matched indices has no `@timestamp`. Aggregation-only queries (`size: 0`)
    return no hits to order, so sorting them is pure overhead.
    """
    if not isinstance(dsl, dict) or "sort" in dsl or dsl.get("size") == 0:
        return dsl
    return {**dsl, "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "date"}}]}


def _reject_cross_index_reads(key: str, value: Any) -> None:
    """Refuse the two query forms that read a document from another index.

    The index whitelist is enforced on the index a request *targets*, which is
    the only index anyone reviewing a DSL thinks it can reach. These two forms
    quietly reach a second one:

      {"terms": {"user": {"index": "secrets", "id": "1", "path": "token"}}}
      {"more_like_this": {"like": [{"_index": "secrets", "_id": "1"}]}}

    Both make ES fetch from `secrets` while the search itself runs against a
    whitelisted index, so the whitelist never sees it. Neither form is
    something NL->DSL generates, so refusing them costs nothing real.
    """
    if key == "terms" and isinstance(value, dict):
        for field_value in value.values():
            if isinstance(field_value, dict) and "index" in field_value:
                raise ValueError(
                    "Forbidden DSL: terms lookup reads another index, "
                    "which bypasses the index whitelist."
                )
    elif key == "more_like_this" and isinstance(value, dict):
        for docs_key in ("like", "unlike"):
            docs = value.get(docs_key)
            for doc in docs if isinstance(docs, list) else [docs]:
                if isinstance(doc, dict) and "_index" in doc:
                    raise ValueError(
                        f"Forbidden DSL: more_like_this {docs_key} references another "
                        "index, which bypasses the index whitelist."
                    )


def _scan(obj: Any, depth: int, counter: list[int]) -> None:
    if depth > 30:
        raise ValueError("DSL nesting too deep.")
    counter[0] += 1
    if counter[0] > _MAX_NODES:
        raise ValueError("DSL too large.")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _FORBIDDEN_KEYS:
                raise ValueError(f"Forbidden DSL key: {k}")
            _reject_cross_index_reads(k, v)
            _scan(v, depth + 1, counter)
    elif isinstance(obj, list):
        for item in obj:
            _scan(item, depth + 1, counter)
