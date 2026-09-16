"""界面上选的时间范围，落到查询上。

问题里说的时间（「最近 30 分钟」）由模型写进 DSL；选择器选的时间是页面的状态。
两者同时存在时**默认不做 AND** —— 那会让「我明明选了昨晚」的查询返回空，然后客户
去排查一个不存在的数据问题。所以：能安全替换的就替换，选择器是唯一的时间来源。

但模型写的时间条件不总是「一个窗口」，有时是**一个形状**。提示词专门教了一种：
「最近 3 天每天凌晨 00:00-06:00」写成 should 里三个 range 加 minimum_should_match。
把它们剥掉会剩下 `should: []` 配 `minimum_should_match: 1` —— 一条都匹配不上，
界面上是一个没有任何提示的空结果。这类只相交，不替换（``_replaceable`` 判形状）。

为什么在执行层而不是提示词里：写进提示词是一个请求，模型可能不照做；而且用户在
界面上改一次 DSL 那句话就没了。在发给 ES 之前包一层是一个保证。

对原条件做了什么必须显示出来（``MODE_*``）—— 悄悄改写用户的查询比不改更糟。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

#: 找不到更好的候选时用它。绝大多数 ECS 索引都是这个。
_PREFERRED = ("@timestamp", "timestamp", "event.ingested", "time")


def resolve_time_field(mapping: dict[str, Any] | None) -> str | None:
    """从 mapping 里挑出这个索引的时间字段。挑不出来返回 None。

    不写死 `@timestamp`：客户的索引不一定用它，写死的结果是范围静默失效 —— 用户
    以为筛了，其实没有。返回 None 的场合调用方要把「未生效」说出来。
    """
    dates = sorted(_date_fields(mapping or {}))
    if not dates:
        return None
    for name in _PREFERRED:
        if name in dates:
            return name
    # 只有一个日期字段就是它；多个又都不在优先表里，选最短的那个 —— 顶层的
    # `timestamp` 比 `event.created`、`file.mtime` 这类更可能是主时间轴。
    return min(dates, key=lambda f: (f.count("."), len(f)))


def _date_fields(mapping: dict[str, Any], prefix: str = "") -> set[str]:
    """展平 mapping，取出所有 date 字段的点路径。

    传进来的可能是 `{index: {mappings: {properties: …}}}`（ES 原样返回），也可能
    已经剥到 `properties` —— 两种都认，调用方少一层拆包。
    """
    out: set[str] = set()
    if not isinstance(mapping, dict):
        return out

    props = mapping.get("properties")
    if props is None:
        # 还没到 properties：往下钻一层（index → mappings → properties）。
        for key, value in mapping.items():
            if isinstance(value, dict):
                out |= _date_fields(value, prefix if key in ("mappings",) else prefix)
        return out

    for name, spec in props.items():
        if not isinstance(spec, dict):
            continue
        path = f"{prefix}{name}"
        if spec.get("type") in ("date", "date_nanos"):
            out.add(path)
        if "properties" in spec:
            out |= _date_fields(spec, f"{path}.")
    return out


def _count_time_ranges(node: Any, field: str) -> int:
    """整棵查询里有几个针对 ``field`` 的 range 子句。"""
    if isinstance(node, dict):
        n = 1 if ("range" in node and isinstance(node["range"], dict)
                  and field in node["range"]) else 0
        return n + sum(_count_time_ranges(v, field) for k, v in node.items() if k != "range")
    if isinstance(node, list):
        return sum(_count_time_ranges(v, field) for v in node)
    return 0


def _replaceable(query: Any, field: str) -> bool:
    """这个查询里的时间条件能不能被安全替换成一个窗口。

    能替换的只有一种形状：**顶层 bool 的 filter / must 里恰好一个**时间 range
    （或者整个 query 就是那一个 range）。它表达的是「一个窗口」，换掉它等于换窗口。

    不能替换的是那些时间条件表达的不是窗口而是**形状**的写法。提示词专门教了模型
    一种：「最近 3 天每天凌晨 00:00-06:00」写成 should 里三个 range 加
    minimum_should_match。把它们剥掉，剩下 `should: []` 配 `minimum_should_match: 1`
    —— 一条都匹配不上，界面上是一个没有任何提示的空结果。must_not（「排除某段
    时间」）同理，剥掉等于把用户的排除条件删了。

    这类只能相交：在原条件之上再 AND 一个窗口。相交可能为空，但那是用户两个条件
    的真实结果，不是我们弄丢的。
    """
    total = _count_time_ranges(query, field)
    if total == 0:
        return False
    if isinstance(query, dict) and total == 1:
        if "range" in query and isinstance(query["range"], dict) and field in query["range"]:
            return True
        b = query.get("bool")
        if isinstance(b, dict):
            # 只看 filter / must 两个数组的直接成员 —— 嵌套更深的位置说明它是
            # 某个组合条件的一部分，单独抽走会改变那个组合的含义。
            for key in ("filter", "must"):
                v = b.get(key)
                items = v if isinstance(v, list) else [v] if isinstance(v, dict) else []
                for item in items:
                    if (isinstance(item, dict) and "range" in item
                            and isinstance(item["range"], dict) and field in item["range"]):
                        return True
    return False


def _strip_ranges(node: Any, field: str) -> tuple[Any, int]:
    """递归删掉所有针对 ``field`` 的 range 子句，返回 (新节点, 删掉几个)。

    删的是子句本身而不是整棵 bool：查询里除了时间还有别的条件（严重度、主机名），
    那些是用户真正问的东西。
    """
    removed = 0
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "range" and isinstance(value, dict) and field in value:
                rest = {k: v for k, v in value.items() if k != field}
                removed += 1
                if rest:
                    out[key] = rest   # 同一个 range 里还有别的字段，留着
                continue
            new_value, n = _strip_ranges(value, field)
            removed += n
            out[key] = new_value
        # `{"range": {...}}` 被清空后剩下一个空 dict —— 那在 bool 的 filter 数组里
        # 是一个非法子句，得整个去掉。
        return ({k: v for k, v in out.items() if not (k == "range" and v == {})}, removed)
    if isinstance(node, list):
        items = []
        for item in node:
            new_item, n = _strip_ranges(item, field)
            removed += n
            # 上面清空的子句在这里落成 `{}`，直接丢掉。
            if new_item != {}:
                items.append(new_item)
        return items, removed
    return node, removed


#: 这次对原有时间条件做了什么。界面要按它说不同的话。
MODE_ADDED = "added"            # 原来没有时间条件
MODE_REPLACED = "replaced"      # 换掉了原来那个窗口
MODE_INTERSECTED = "intersected"  # 原条件是个形状，只能再 AND 一层
MODE_QUESTION_WINS = "question_wins"  # 问题里明确说了时间，筛选器让位并同步过去


def apply_window(
    dsl: dict[str, Any],
    field: str,
    since: str | None,
    until: str | None = None,
) -> tuple[dict[str, Any], str]:
    """给 DSL 套上时间窗，返回 (新 DSL, 对原有时间条件做了什么)。

    没有 since 也没有 until 就原样返回 —— 「全部时间」是默认值，不该改变任何东西。
    """
    if not since and not until:
        return dsl, MODE_ADDED

    out = deepcopy(dsl)
    if _replaceable(out.get("query"), field):
        stripped, removed = _strip_ranges(out.get("query"), field)
        if "query" in out:
            out["query"] = stripped
        mode = MODE_REPLACED if removed else MODE_ADDED
    else:
        # 形状留着，只在它之上再加一层窗口。
        mode = MODE_INTERSECTED if _count_time_ranges(out.get("query"), field) else MODE_ADDED

    bounds: dict[str, str] = {}
    if since:
        bounds["gte"] = since
    if until:
        bounds["lte"] = until
    clause = {"range": {field: bounds}}

    existing = out.get("query")
    if isinstance(existing, dict) and isinstance(existing.get("bool"), dict):
        # 已经是 bool：挂进 filter，不动 must/should 的打分语义。
        b = existing["bool"]
        flt = b.get("filter")
        if isinstance(flt, list):
            b["filter"] = [*flt, clause]
        elif isinstance(flt, dict):
            b["filter"] = [flt, clause]
        else:
            b["filter"] = [clause]
    elif isinstance(existing, dict) and existing:
        # 别的单子句（match / term / query_string）：包成 bool，原子句进 must
        # 而不是 filter —— 它可能是要打分的。
        out["query"] = {"bool": {"must": [existing], "filter": [clause]}}
    else:
        out["query"] = {"bool": {"filter": [clause]}}

    return out, mode
