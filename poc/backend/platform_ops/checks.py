"""Deterministic verdicts over the read-only probes in `probe.py`.

P0 is rule-based on purpose: a customer running this unattended needs the
same answer every time for the same cluster state, and an LLM call per check
would burn tokens on something a threshold comparison already answers
exactly. Each check degrades to UNKNOWN instead of raising — a customer ES
account missing `monitor` privileges on one API must not blank out every
other check in the report.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from ..index_whitelist import get as get_whitelist
from . import probe

logger = logging.getLogger("rst.platform_ops")

OK = "ok"
WARN = "warn"
FAIL = "fail"
UNKNOWN = "unknown"

_SEVERITY = {OK: 0, UNKNOWN: 1, WARN: 2, FAIL: 3}

# Disk watermarks mirror ES's own default flood-stage/high-watermark shape —
# these are only for our own WARN/OK labeling, not sent to the cluster.
DEFAULT_DISK_WARN_PCT = 90
DEFAULT_DISK_NOTE_PCT = 85

DEFAULT_STALE_WARN_H = 6
DEFAULT_STALE_FAIL_H = 24

# 时间基线。「领先」的容忍度比「落后」小得多：日志落后几小时可能只是采集慢，
# 领先则一定有东西错了 —— 未来的日志不存在。
DEFAULT_AHEAD_WARN_MIN = 5
DEFAULT_AHEAD_FAIL_MIN = 30
# 采集延迟到这个数就值得说一句：用户问「最近 5 分钟」会查出空。
DEFAULT_LAG_NOTE_S = 120


def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name, "").strip())
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def _disk_warn_pct() -> int:
    return _env_int("RST_OPS_DISK_WARN_PCT", DEFAULT_DISK_WARN_PCT)


def _disk_note_pct() -> int:
    return _env_int("RST_OPS_DISK_NOTE_PCT", DEFAULT_DISK_NOTE_PCT)


def _stale_warn_h() -> int:
    return _env_int("RST_OPS_STALE_WARN_H", DEFAULT_STALE_WARN_H)


def _stale_fail_h() -> int:
    return _env_int("RST_OPS_STALE_FAIL_H", DEFAULT_STALE_FAIL_H)


def _ahead_warn_min() -> int:
    return _env_int("RST_OPS_AHEAD_WARN_MIN", DEFAULT_AHEAD_WARN_MIN)


def _ahead_fail_min() -> int:
    return _env_int("RST_OPS_AHEAD_FAIL_MIN", DEFAULT_AHEAD_FAIL_MIN)


def _lag_note_s() -> int:
    return _env_int("RST_OPS_LAG_NOTE_S", DEFAULT_LAG_NOTE_S)


def _parse_iso(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


def _result(id_: str, title: str, verdict: str, summary: str, detail: dict, advice: str) -> dict:
    return {
        "id": id_,
        "title": title,
        "verdict": verdict,
        "summary": summary,
        "detail": detail,
        "advice": advice,
    }


def _unknown(id_: str, title: str, reason: str) -> dict:
    return _result(id_, title, UNKNOWN, f"无法检查：{reason}", {}, "")


async def check_cluster_health() -> dict:
    data, err = await probe.cluster_health()
    if err:
        return _unknown("cluster_health", "集群健康状态", err)

    status = data.get("status")
    n_data_nodes = data.get("number_of_data_nodes", 0)
    unassigned = data.get("unassigned_shards", 0)
    active_pct = data.get("active_shards_percent_as_number")
    detail = {
        "status": status,
        "number_of_data_nodes": n_data_nodes,
        "unassigned_shards": unassigned,
        "active_shards_percent_as_number": active_pct,
    }

    if status == "red":
        return _result(
            "cluster_health", "集群健康状态", FAIL,
            "集群状态为 red：存在主分片不可用，写入/查询可能已受影响。",
            detail,
            "请尽快检查节点是否宕机、磁盘是否已满，并查看未分配分片检查项的具体原因。",
        )
    if status == "yellow":
        if n_data_nodes == 1:
            return _result(
                "cluster_health", "集群健康状态", WARN,
                f"集群状态为 yellow，但当前只有 1 个数据节点：{unassigned} 个副本分片无处分配，"
                "这是单节点集群的预期状态，不代表故障。生产多节点环境下出现同样的 yellow 状态则需要排查。",
                detail,
                "单节点开发/测试环境可忽略；如果这是生产集群，请检查节点数量是否符合预期。",
            )
        return _result(
            "cluster_health", "集群健康状态", FAIL,
            f"集群状态为 yellow，且有 {n_data_nodes} 个数据节点：副本分片未能分配不是单节点场景，需要排查。",
            detail,
            "请查看未分配分片检查项的具体原因（磁盘水位、分配设置、节点下线等）。",
        )
    return _result("cluster_health", "集群健康状态", OK, "集群状态为 green。", detail, "")


async def check_unassigned_shards(is_real_problem: bool = False) -> dict:
    """Report the reason behind unassigned shards.

    `is_real_problem` is decided by the caller (`run_all`) from
    `check_cluster_health`'s verdict: True only for a genuine fault (red, or
    yellow on a multi-node cluster). A single-node yellow is expected
    shard-placement, so callers should pass False there and this function
    skips the extra `allocation_explain` call entirely — no point spending it
    when we already know the answer is "nowhere to put the replica".
    """
    if not is_real_problem:
        return _result(
            "unassigned_shards", "未分配分片原因", OK,
            "集群健康检查未发现需要深入排查的未分配分片。", {}, "",
        )

    shards, err = await probe.cat_shards()
    if err:
        return _unknown("unassigned_shards", "未分配分片原因", err)

    unassigned = [s for s in shards if s.get("state") == "UNASSIGNED"]
    if not unassigned:
        return _result(
            "unassigned_shards", "未分配分片原因", OK, "未检测到未分配分片。", {}, "",
        )

    explain, _explain_err = await probe.allocation_explain()
    reason = None
    if explain:
        reason = (explain.get("unassigned_info") or {}).get("reason")

    sample = [
        {"index": s.get("index"), "shard": s.get("shard"), "prirep": s.get("prirep")}
        for s in unassigned[:10]
    ]
    return _result(
        "unassigned_shards", "未分配分片原因", FAIL,
        f"发现 {len(unassigned)} 个未分配分片" + (f"，示例原因：{reason}。" if reason else "。"),
        {"count": len(unassigned), "sample": sample, "reason": reason},
        "请根据 allocation explain 的原因处理：常见为磁盘水位触发只读、节点下线或分配规则限制。",
    )


async def check_thread_pool_rejections() -> dict:
    data, err = await probe.nodes_thread_pool_stats()
    if err:
        return _unknown("thread_pool_rejections", "线程池拒绝计数", err)

    per_node = {}
    any_rejected = False
    for node_id, node in (data.get("nodes") or {}).items():
        pools = node.get("thread_pool", {})
        name = node.get("name", node_id)
        node_detail = {}
        for pool_name in ("write", "search"):
            rejected = (pools.get(pool_name) or {}).get("rejected", 0)
            node_detail[pool_name] = rejected
            if rejected > 0:
                any_rejected = True
        per_node[name] = node_detail

    verdict = WARN if any_rejected else OK
    summary = (
        "存在写入/查询线程池拒绝（累计值，非当前速率）：可能曾经历过压力高峰或分片过多，"
        "不代表现在仍在丢数据，但值得关注趋势。"
        if any_rejected else
        "写入/查询线程池未出现过拒绝。"
    )
    advice = (
        "该计数自节点启动以来累计，无法直接判断当前状态。建议结合监控看板观察 rejected 是否持续增长，"
        "或重启节点后重新观察一段时间。"
        if any_rejected else ""
    )
    return _result("thread_pool_rejections", "线程池拒绝计数", verdict, summary, per_node, advice)


async def check_disk_watermark() -> dict:
    alloc, err = await probe.cat_allocation()
    blocks, blocks_err = await probe.index_settings_blocks()

    if err and blocks_err:
        return _unknown("disk_watermark", "磁盘水位与只读块", err)

    blocked_indices = []
    if blocks:
        for name, settings in blocks.items():
            ro = (
                (settings.get("settings") or {})
                .get("index", {})
                .get("blocks", {})
                .get("read_only_allow_delete")
            )
            if str(ro).lower() == "true":
                blocked_indices.append(name)

    if blocked_indices:
        return _result(
            "disk_watermark", "磁盘水位与只读块", FAIL,
            f"发现 {len(blocked_indices)} 个索引被磁盘水位触发为只读，这是日志“突然不进了”最常见的原因。",
            {"read_only_indices": blocked_indices},
            "请先清理磁盘空间或扩容，确认磁盘使用率降到安全水位后，再手动解除只读块，例如：\n"
            'PUT /<index>/_settings\n{"index.blocks.read_only_allow_delete": null}',
        )

    max_pct = None
    per_node = []
    if alloc:
        for row in alloc:
            pct_raw = row.get("disk.percent")
            try:
                pct = float(pct_raw) if pct_raw not in (None, "") else None
            except (TypeError, ValueError):
                pct = None
            per_node.append({"node": row.get("node"), "disk.percent": pct})
            if pct is not None and (max_pct is None or pct > max_pct):
                max_pct = pct

    if max_pct is not None and max_pct >= _disk_warn_pct():
        return _result(
            "disk_watermark", "磁盘水位与只读块", WARN,
            f"存在节点磁盘使用率达到 {max_pct:.0f}%，接近/超过水位线（{_disk_warn_pct()}%），"
            "如不处理可能很快触发只读块。",
            {"nodes": per_node},
            "建议尽快清理旧索引（配合 ILM）或扩容磁盘。",
        )
    if max_pct is not None and max_pct >= _disk_note_pct():
        return _result(
            "disk_watermark", "磁盘水位与只读块", OK,
            f"磁盘使用率已到 {max_pct:.0f}%，暂未到告警线（{_disk_warn_pct()}%），建议关注趋势。",
            {"nodes": per_node}, "",
        )
    return _result(
        "disk_watermark", "磁盘水位与只读块", OK,
        "磁盘使用率正常，未发现只读块。" if alloc is not None else "未发现只读块。",
        {"nodes": per_node}, "",
    )


async def check_ilm_errors() -> dict:
    data, err = await probe.ilm_explain()
    if err:
        return _unknown("ilm_errors", "ILM 生命周期错误", err)
    if not data:
        return _unknown("ilm_errors", "ILM 生命周期错误", "未启用 ILM 或无可用信息")

    errored = []
    for name, info in (data.get("indices") or {}).items():
        if info.get("step") == "ERROR":
            step_info = info.get("step_info") or {}
            errored.append({"index": name, "reason": step_info.get("reason")})

    if not errored:
        return _result("ilm_errors", "ILM 生命周期错误", OK, "未发现处于 ERROR 步骤的索引。", {}, "")

    return _result(
        "ilm_errors", "ILM 生命周期错误", WARN,
        f"有 {len(errored)} 个索引的 ILM 处于 ERROR 步骤，可能导致索引无法按预期滚动/删除。",
        {"errored": errored},
        "请根据每个索引的 reason 处理（常见为策略引用了不存在的 phase，或分片分配失败），"
        "处理后可执行 POST /<index>/_ilm/retry 重试。",
    )


async def check_ingest_freshness(whitelist_patterns: list[str] | None = None) -> dict:
    """Freshest possible signal for "is ingest actually flowing" — a data
    stream can look otherwise healthy while nothing has landed in it for
    days. Filtered by the index whitelist because that's this deployment's
    own declaration of which indices it cares about; nothing here should
    look past that boundary.

    `whitelist_patterns` lets callers/tests pass patterns explicitly; when
    omitted this reads the process-wide whitelist singleton.
    """
    streams, err = await probe.data_streams()
    if err:
        return _unknown("ingest_freshness", "日志接入新鲜度", err)

    whitelist = get_whitelist()
    if whitelist_patterns is not None:
        from ..index_whitelist import IndexWhitelist
        whitelist = IndexWhitelist(whitelist_patterns)

    names = [s.get("name") for s in (streams or []) if s.get("name")]
    if whitelist.is_active():
        names = [n for n in names if whitelist.is_allowed(n)]

    if not names:
        return _result(
            "ingest_freshness", "日志接入新鲜度", UNKNOWN,
            "没有匹配白名单的数据流可供检查。", {}, "",
        )

    now = datetime.now(timezone.utc)
    entries = []
    worst = OK
    for name in names:
        ts, ts_err = await probe.last_doc_time(name)
        if ts_err or not ts:
            entries.append({"data_stream": name, "last_doc_time": None, "hours_since": None, "verdict": UNKNOWN})
            if _SEVERITY[UNKNOWN] > _SEVERITY[worst]:
                worst = UNKNOWN
            continue
        try:
            last_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            entries.append({"data_stream": name, "last_doc_time": ts, "hours_since": None, "verdict": UNKNOWN})
            if _SEVERITY[UNKNOWN] > _SEVERITY[worst]:
                worst = UNKNOWN
            continue

        hours = (now - last_dt).total_seconds() / 3600
        if hours >= _stale_fail_h():
            v = FAIL
        elif hours >= _stale_warn_h():
            v = WARN
        else:
            v = OK
        entries.append({"data_stream": name, "last_doc_time": ts, "hours_since": round(hours, 1), "verdict": v})
        if _SEVERITY[v] > _SEVERITY[worst]:
            worst = v

    if worst == OK:
        summary = "所有受检数据流均在近期有新数据写入。"
    elif worst == UNKNOWN:
        summary = "部分数据流无法获取最后写入时间（可能为空索引或缺少 @timestamp 字段）。"
    else:
        stale = [e for e in entries if e["verdict"] in (WARN, FAIL)]
        summary = "以下数据流的最后写入时间超过阈值，接入可能已中断：" + "、".join(
            f"{e['data_stream']}({e['hours_since']}h)" for e in stale
        )

    advice = (
        "请检查对应数据源的采集端（Agent/Beats/Logstash/Fluent 等）是否在运行，"
        "以及网络/认证是否正常。" if worst in (WARN, FAIL) else ""
    )
    return _result("ingest_freshness", "日志接入新鲜度", worst, summary, {"data_streams": entries}, advice)


async def check_time_baseline(whitelist_patterns: list[str] | None = None) -> dict:
    """索引里的时间和真实时间对不对得上。

    这条检查存在的理由：时间错了的现象是**查不到数据，而且不报错**。客户问
    「今天下午登录失败最多的 IP」，拿到零条，然后去排查一个不存在的故障 —— 真正
    的原因是采集端把本地时间当 UTC 写进去了，整个索引偏移 8 小时。

    三种成因分开判，因为修法完全不同：

      领先 now      采集端时区配错，或机器时钟快了 —— 未来的日志不存在
      按主机参差    那几台没配 NTP，不是全局时区问题
      采集延迟      不是错误。但「最近 5 分钟查不到」要靠它解释

    产品不替客户改数据：ES 的 date 字段内部存的是 UTC epoch，错是错在写入那一刻，
    要真正修好只能改采集配置或 reindex —— 那是客户的集群。这里只给结论和处置方向。
    """
    streams, err = await probe.data_streams()
    if err:
        return _unknown("time_baseline", "时间基线", err)

    whitelist = get_whitelist()
    if whitelist_patterns is not None:
        from ..index_whitelist import IndexWhitelist
        whitelist = IndexWhitelist(whitelist_patterns)

    names = [s.get("name") for s in (streams or []) if s.get("name")]
    if whitelist.is_active():
        names = [n for n in names if whitelist.is_allowed(n)]
    if not names:
        return _result("time_baseline", "时间基线", UNKNOWN,
                       "没有匹配白名单的数据流可供检查。", {}, "")

    now = datetime.now(timezone.utc)
    entries: list[dict] = []
    worst = OK
    ahead: list[dict] = []
    skewed_hosts: list[dict] = []
    lag_s: float | None = None
    hosts_seen = 0

    for name in names:
        base, base_err = await probe.time_baseline(name)
        if base_err or not base:
            entries.append({"data_stream": name, "verdict": UNKNOWN, "error": base_err})
            if _SEVERITY[UNKNOWN] > _SEVERITY[worst]:
                worst = UNKNOWN
            continue

        newest = _parse_iso(base.get("newest"))
        if newest is None:
            entries.append({"data_stream": name, "verdict": UNKNOWN, "error": "没有 @timestamp"})
            if _SEVERITY[UNKNOWN] > _SEVERITY[worst]:
                worst = UNKNOWN
            continue

        ahead_min = (newest - now).total_seconds() / 60
        v = OK
        if ahead_min >= _ahead_fail_min():
            v = FAIL
        elif ahead_min >= _ahead_warn_min():
            v = WARN
        if v != OK:
            ahead.append({"data_stream": name, "ahead_minutes": round(ahead_min, 1)})

        # 只报**领先**的主机。落后不是这条检查能确诊的：一台机器安静一小时可能
        # 只是它没什么日志，而「采集停了」已经由 check_ingest_freshness 管着 ——
        # 拿落后去猜时钟偏移，会把每一台安静的主机都报成故障（真跑演示数据时
        # 一次报了 5 台，全是误报）。领先则不同：未来的日志不存在，只能是时钟快了。
        for h in base.get("hosts") or []:
            t = _parse_iso(h.get("newest"))
            if t is None:
                continue
            hosts_seen += 1
            ahead_host_min = (t - now).total_seconds() / 60
            if ahead_host_min >= _ahead_warn_min():
                skewed_hosts.append({"data_stream": name, "host": h.get("host"),
                                     "ahead_minutes": round(ahead_host_min, 1)})

        p50 = (base.get("lag_ms") or {}).get("50.0")
        if isinstance(p50, (int, float)) and p50 > 0:
            lag_s = max(lag_s or 0, p50 / 1000)

        entries.append({
            "data_stream": name,
            "newest": base.get("newest"),
            "oldest": base.get("oldest"),
            "ahead_minutes": round(ahead_min, 1),
            "verdict": v,
        })
        if _SEVERITY[v] > _SEVERITY[worst]:
            worst = v

    if skewed_hosts and _SEVERITY[WARN] > _SEVERITY[worst]:
        worst = WARN

    parts: list[str] = []
    if ahead:
        parts.append(
            "以下数据流里出现了「未来」的日志（最新一条比当前时间还晚）："
            + "、".join(f"{a['data_stream']}(+{a['ahead_minutes']}分钟)" for a in ahead)
        )
    if skewed_hosts:
        parts.append(
            "以下主机写入了「未来」的日志（时钟快于网关）："
            + "、".join(f"{h['host']}(+{h['ahead_minutes']}分钟)" for h in skewed_hosts[:5])
        )
    if lag_s and lag_s >= _lag_note_s():
        parts.append(f"采集延迟中位数约 {int(lag_s)} 秒，问「最近 1 分钟」这类窗口会查不到东西。")
    summary = "；".join(parts) if parts else "索引时间与网关时间一致，未发现时区或时钟偏差。"

    # 一台机器时钟快，整条流的 max 也会跟着领先 —— 两个信号是耦合的。真正能
    # 区分成因的是**范围**：全体偏移 = 采集端时区配错；只有个别主机偏 = 那几台的
    # 系统时钟。
    partial = bool(skewed_hosts) and hosts_seen >= 2 and len(skewed_hosts) < hosts_seen

    advice = ""
    if ahead and partial:
        advice = (
            "只有部分主机领先，其余正常。这是那几台的系统时钟快了，不是采集端时区"
            "配置问题。检查它们的 NTP（chronyd / ntpd）。"
        )
    elif ahead:
        advice = (
            "「未来的日志」几乎只有两个原因：采集端把本地时间当 UTC 写入（Filebeat / "
            "Logstash / ingest pipeline 的 date 处理缺 timezone），或者数据源主机时钟快了。"
            "偏移量接近整小时（如 +480 分钟）时基本可以断定是前者。修在采集端，ES 的 "
            "date 字段存的是 UTC 时刻，已写入的数据只能 reindex，本产品不代改。"
        )
    elif skewed_hosts:
        advice = (
            "这些主机的系统时钟快于网关，检查它们的 NTP（chronyd / ntpd）。"
            "只有个别主机偏、其余正常时，是单机时钟问题，不是采集端时区配置问题。"
        )
    elif lag_s and lag_s >= _lag_note_s():
        advice = "延迟本身不是故障，但提问时把窗口放宽到延迟的两倍以上，否则会查到空结果。"

    return _result("time_baseline", "时间基线", worst, summary, {
        "gateway_now": now.isoformat(),
        "data_streams": entries,
        "skewed_hosts": skewed_hosts,
        "ingest_lag_seconds_p50": round(lag_s, 1) if lag_s else None,
    }, advice)

_CHECK_FNS = (
    "check_cluster_health",
    "check_unassigned_shards",
    "check_thread_pool_rejections",
    "check_disk_watermark",
    "check_ilm_errors",
    "check_ingest_freshness",
    "check_time_baseline",
)

_TITLES = {
    "check_cluster_health": "集群健康状态",
    "check_unassigned_shards": "未分配分片原因",
    "check_thread_pool_rejections": "线程池拒绝计数",
    "check_disk_watermark": "磁盘水位与只读块",
    "check_ilm_errors": "ILM 生命周期错误",
    "check_ingest_freshness": "日志接入新鲜度",
    "check_time_baseline": "时间基线",
}


async def run_all() -> dict:
    results: list[dict] = []

    health = await _safe_run("check_cluster_health", check_cluster_health())
    results.append(health)

    real_problem = health.get("verdict") == FAIL
    results.append(await _safe_run("check_unassigned_shards", check_unassigned_shards(real_problem)))
    results.append(await _safe_run("check_thread_pool_rejections", check_thread_pool_rejections()))
    results.append(await _safe_run("check_disk_watermark", check_disk_watermark()))
    results.append(await _safe_run("check_ilm_errors", check_ilm_errors()))
    results.append(await _safe_run("check_ingest_freshness", check_ingest_freshness()))
    results.append(await _safe_run("check_time_baseline", check_time_baseline()))

    counts = {OK: 0, WARN: 0, FAIL: 0, UNKNOWN: 0}
    overall = OK
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        if _SEVERITY[r["verdict"]] > _SEVERITY[overall]:
            overall = r["verdict"]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": overall,
        "counts": counts,
        "checks": results,
    }


async def _safe_run(name: str, coro) -> dict:
    # A single check's bug (or an unexpected ES response shape) must not take
    # down the whole report — the customer still gets every other verdict.
    try:
        return await coro
    except Exception as e:
        logger.warning("check_failed", extra={"check": name, "error": str(e)})
        return _unknown(name.removeprefix("check_"), _TITLES.get(name, name), f"内部错误：{e}")
