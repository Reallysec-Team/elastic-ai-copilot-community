"""判定引擎编排单测（TDD）—— 全 mock reader/store，验证端到端判定 + 评分。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.baseline import engine  # noqa: E402
from backend.baseline.schema import Rule  # noqa: E402

_NOW = "2026-07-04T12:00:00Z"

_RULES = [
    Rule.from_dict({
        "rule_id": "HB-ACC-001", "title": "UID=0 唯一性", "category": "账户", "platform": "linux",
        "severity": "high", "standard_refs": ["等保X", "CIS-Y"],
        "collect": {"query": "SELECT ..."},
        "judge": {"operator": "expect_empty", "on_missing": "pass"},
        "remediation_template": "删除越权账户",
    }),
    Rule.from_dict({
        "rule_id": "HB-NET-003", "title": "IP 转发关闭", "category": "网络", "platform": "linux",
        "severity": "medium", "collect": {"query": "SELECT ..."},
        "judge": {"operator": "equals", "field": "current_value", "expected": "0", "on_missing": "fail"},
        "remediation_template": "sysctl ...",
    }),
]


def _install(monkeypatch, rows_map, hosts=("web01",), last_seen=_NOW, collected=_NOW,
             platforms=None):
    """last_seen / collected 默认与 _NOW 同刻 —— 数据新鲜，走正常判定路径。
    platforms：host → "linux"/"windows"；缺省 None = 上报里没有 host.os.*，全规则都跑。"""
    async def _load_rules():
        return list(_RULES)

    async def _host_platform(host):
        return (platforms or {}).get(host)

    async def _list_hosts():
        return list(hosts)

    async def _fetch_latest(host, rule_id):
        return rows_map.get((host, rule_id), []), collected

    async def _host_last_seen(host):
        return last_seen

    written = {"results": None, "run": None}

    async def _write_results(run_id, results):
        written["results"] = results

    async def _write_run(summary):
        written["run"] = summary

    monkeypatch.setattr(engine.store, "load_enabled_rules", _load_rules)
    monkeypatch.setattr(engine.store, "write_results", _write_results)
    monkeypatch.setattr(engine.store, "write_run", _write_run)
    monkeypatch.setattr(engine.result_reader, "list_hosts", _list_hosts)
    monkeypatch.setattr(engine.result_reader, "fetch_latest", _fetch_latest)
    monkeypatch.setattr(engine.result_reader, "host_last_seen", _host_last_seen)
    monkeypatch.setattr(engine.result_reader, "host_platform", _host_platform)
    return written


def test_run_judges_pass_and_fail(monkeypatch):
    rows_map = {
        ("web01", "HB-ACC-001"): [],                                   # expect_empty → pass
        ("web01", "HB-NET-003"): [{"current_value": "1"}],             # equals 0 → fail
    }
    written = _install(monkeypatch, rows_map)
    summary = asyncio.run(engine.run_baseline("run-1", now_iso=_NOW))

    assert summary["pass"] == 1
    assert summary["fail"] == 1
    assert summary["host_count"] == 1
    assert summary["rule_count"] == 2
    assert summary["score"] == 50.0
    verdicts = {r.rule_id: r.verdict for r in written["results"]}
    assert verdicts == {"HB-ACC-001": "pass", "HB-NET-003": "fail"}


def test_fail_result_carries_static_remediation(monkeypatch):
    rows_map = {("web01", "HB-NET-003"): [{"current_value": "1"}]}
    written = _install(monkeypatch, rows_map)
    asyncio.run(engine.run_baseline("run-2", now_iso=_NOW))
    fail = next(r for r in written["results"] if r.rule_id == "HB-NET-003")
    assert fail.remediation == "sysctl ..."   # 取规则静态模板
    assert fail.actual == "current_value=1"
    assert fail.standard_refs == ()  # 该规则没配 refs
    assert fail.checked_at == _NOW


def test_pass_result_has_no_remediation(monkeypatch):
    rows_map = {("web01", "HB-ACC-001"): []}
    written = _install(monkeypatch, rows_map, hosts=("web01",))
    # 只保留一条规则以简化
    monkeypatch.setattr(engine.store, "load_enabled_rules",
                        lambda: _asyncval([_RULES[0]]))
    asyncio.run(engine.run_baseline("run-3", now_iso=_NOW))
    r = written["results"][0]
    assert r.verdict == "pass"
    assert r.remediation == ""  # pass 不带整改


def test_score_is_unevaluated_not_100_when_nothing_is_judgeable(monkeypatch):
    # 全 manual/error → 分母 0 → 未评估（None），不是 100。
    # 100 的含义是“检查过、全部通过”，而分母为 0 的真实含义恰恰相反：一条都没评上。
    # 规则库为空（种子写入因 ES 写权限失败）或无主机上报也走这里，记 100 会让
    # 记分板对一台从未被检查的机器显示“完全合规”。
    rule = Rule.from_dict({
        "rule_id": "HB-SYS-001", "title": "EOL", "category": "系统", "platform": "linux",
        "severity": "medium", "collect": {"query": "x"},
        "judge": {"operator": "manual_review", "on_missing": "error"},
    })
    monkeypatch.setattr(engine.store, "load_enabled_rules", lambda: _asyncval([rule]))
    _install(monkeypatch, {})  # monkeypatch side effects only; results unused
    monkeypatch.setattr(engine.store, "load_enabled_rules", lambda: _asyncval([rule]))
    summary = asyncio.run(engine.run_baseline("run-4", now_iso=_NOW))
    assert summary["manual_review"] == 1
    assert summary["score"] is None, "未评估 must not render as full compliance"


def test_explicit_hosts_skip_list_hosts(monkeypatch):
    called = {"list": False}
    rows_map = {("db01", "HB-ACC-001"): [], ("db01", "HB-NET-003"): [{"current_value": "0"}]}
    _install(monkeypatch, rows_map)  # monkeypatch side effects only; results unused

    async def _boom():
        called["list"] = True
        return ["should-not-be-used"]

    monkeypatch.setattr(engine.result_reader, "list_hosts", _boom)
    summary = asyncio.run(engine.run_baseline("run-5", hosts=["db01"], now_iso=_NOW))
    assert called["list"] is False
    assert summary["host_count"] == 1
    assert summary["pass"] == 2  # 两条都 pass


def test_eol_operator_routes_to_eol_module(monkeypatch):
    # operator==eol 的规则应走 engine 的 eol 分支（调 eol.judge_eol），
    # 而不是塞进纯函数 operators.evaluate。
    eol_rule = Rule.from_dict({
        "rule_id": "HB-SYS-001", "title": "OS EOL", "category": "系统", "platform": "linux",
        "severity": "medium", "collect": {"query": "SELECT name,version,platform FROM os_version;"},
        "judge": {"operator": "eol", "on_missing": "error"},
        "remediation_template": "升级到受支持版本",
    })
    seen = {"today": None, "rows": None}

    async def _judge_eol(rows, today, lookup=None):
        seen["today"] = today
        seen["rows"] = rows
        return ("fail", "centos 7 已过 EOL")

    monkeypatch.setattr(engine.eol, "judge_eol", _judge_eol)
    monkeypatch.setattr(engine.store, "load_enabled_rules", lambda: _asyncval([eol_rule]))
    rows_map = {("web01", "HB-SYS-001"): [{"name": "CentOS Linux", "version": "7.9.2009"}]}
    written = _install(monkeypatch, rows_map)
    monkeypatch.setattr(engine.store, "load_enabled_rules", lambda: _asyncval([eol_rule]))

    summary = asyncio.run(engine.run_baseline("run-eol", now_iso=_NOW))
    assert summary["fail"] == 1
    r = written["results"][0]
    assert r.verdict == "fail"
    assert r.actual == "centos 7 已过 EOL"
    assert r.remediation == "升级到受支持版本"  # fail 带静态整改
    # eval_date 由 now_iso 派生并注入（确定性、可测）
    from datetime import date
    assert seen["today"] == date(2026, 7, 4)
    assert seen["rows"] == [{"name": "CentOS Linux", "version": "7.9.2009"}]


def test_eol_eval_date_explicit_injection(monkeypatch):
    from datetime import date
    eol_rule = Rule.from_dict({
        "rule_id": "HB-SYS-001", "title": "OS EOL", "category": "系统", "platform": "linux",
        "severity": "medium", "collect": {"query": "x"},
        "judge": {"operator": "eol"},
    })
    seen = {"today": None}

    async def _judge_eol(rows, today, lookup=None):
        seen["today"] = today
        return ("pass", "ok")

    monkeypatch.setattr(engine.eol, "judge_eol", _judge_eol)
    monkeypatch.setattr(engine.store, "load_enabled_rules", lambda: _asyncval([eol_rule]))
    _install(monkeypatch, {("web01", "HB-SYS-001"): [{"name": "Ubuntu", "version": "24.04"}]})
    monkeypatch.setattr(engine.store, "load_enabled_rules", lambda: _asyncval([eol_rule]))
    asyncio.run(engine.run_baseline("run-eol2", now_iso=_NOW, eval_date=date(2030, 1, 1)))
    assert seen["today"] == date(2030, 1, 1)


def test_stale_host_is_stale_not_pass(monkeypatch):
    # 这条钉死整个改动：主机 30 天没上报，expect_empty 规则拿到 0 行，
    # operators.evaluate 对 0 行返回 pass —— 陈旧数据就是这样变成“合规”的。
    # 合规产品里这是最坏方向的错，必须判 stale 且不进评分分母。
    written = _install(monkeypatch, {("web01", "HB-ACC-001"): []},
                       last_seen="2026-06-04T12:00:00Z")
    monkeypatch.setattr(engine.store, "load_enabled_rules", lambda: _asyncval([_RULES[0]]))
    summary = asyncio.run(engine.run_baseline("run-stale", now_iso=_NOW))

    r = written["results"][0]
    assert r.verdict == "stale", "陈旧主机不得判 pass"
    assert "30.0 天前" in r.actual
    assert summary["pass"] == 0
    assert summary["score"] is None, "无可判项 → 未评估，不是 100"
    assert summary["error"] == 1, "stale 并入 error 计数（baseline-runs 是 strict mapping）"


def test_fresh_host_with_no_rows_still_passes(monkeypatch):
    # 反向护栏：主机在正常上报，只是这条 expect_empty 规则本轮没产行 —— 那是
    # 合法的空结果（没有越权账户），不能因为“没数据”就一律判 stale。
    written = _install(monkeypatch, {("web01", "HB-ACC-001"): []}, collected=None)
    monkeypatch.setattr(engine.store, "load_enabled_rules", lambda: _asyncval([_RULES[0]]))
    summary = asyncio.run(engine.run_baseline("run-fresh", now_iso=_NOW))
    assert written["results"][0].verdict == "pass"
    assert summary["pass"] == 1


def test_rule_level_stale_when_host_is_fresh(monkeypatch):
    # 主机在报，但这条规则的采集停了（pack 里被删/查询报错）→ 该项 stale。
    written = _install(monkeypatch, {("web01", "HB-NET-003"): [{"current_value": "0"}]},
                       collected="2026-06-04T12:00:00Z")
    monkeypatch.setattr(engine.store, "load_enabled_rules", lambda: _asyncval([_RULES[1]]))
    asyncio.run(engine.run_baseline("run-rule-stale", now_iso=_NOW))
    r = written["results"][0]
    assert r.verdict == "stale"
    assert r.actual.startswith("该项数据过期")


def test_max_age_disabled_restores_old_behaviour(monkeypatch):
    monkeypatch.setenv("RST_BASELINE_MAX_AGE_HOURS", "0")
    written = _install(monkeypatch, {("web01", "HB-ACC-001"): []},
                       last_seen="2020-01-01T00:00:00Z", collected="2020-01-01T00:00:00Z")
    monkeypatch.setattr(engine.store, "load_enabled_rules", lambda: _asyncval([_RULES[0]]))
    asyncio.run(engine.run_baseline("run-off", now_iso=_NOW))
    assert written["results"][0].verdict == "pass"


def test_host_last_seen_probe_failure_does_not_flag_stale(monkeypatch):
    # ES 抖动 ≠ 主机失联。探测失败要退回正常判定路径（真取数失败自会成 error）。
    written = _install(monkeypatch, {("web01", "HB-ACC-001"): []})

    async def _boom(host):
        raise RuntimeError("es down")

    monkeypatch.setattr(engine.result_reader, "host_last_seen", _boom)
    monkeypatch.setattr(engine.store, "load_enabled_rules", lambda: _asyncval([_RULES[0]]))
    asyncio.run(engine.run_baseline("run-probe-fail", now_iso=_NOW))
    assert written["results"][0].verdict == "pass"


def _asyncval(v):
    async def _f():
        return v
    return _f()


_WIN_RULE = Rule.from_dict({
    "rule_id": "NB-WIN-001", "title": "来宾账户禁用", "category": "账户", "platform": "windows",
    "severity": "medium", "collect": {"query": "SELECT ..."},
    "judge": {"operator": "equals", "field": "data", "expected": "1", "on_missing": "fail"},
    "remediation_template": "net user guest /active:no",
})


def test_rules_of_other_platform_are_skipped_when_platform_known(monkeypatch):
    """Linux 主机不该被 Windows 规则判 fail（on_missing=fail 曾让干净主机全线失分）。"""
    written = _install(monkeypatch, {("web01", "HB-NET-003"): [{"current_value": "0"}]},
                       platforms={"web01": "linux"})
    monkeypatch.setattr(engine.store, "load_enabled_rules",
                        lambda: _asyncval(list(_RULES) + [_WIN_RULE]))
    asyncio.run(engine.run_baseline("run-p1"))
    ids = {r.rule_id for r in written["results"]}
    assert "NB-WIN-001" not in ids
    assert ids == {"HB-ACC-001", "HB-NET-003"}
    assert written["run"]["fail"] == 0


def test_all_rules_run_when_platform_unknown(monkeypatch):
    """没有 host.os.* 的上报 → 平台未知 → 保持旧行为，什么都不跳。"""
    written = _install(monkeypatch, {})
    monkeypatch.setattr(engine.store, "load_enabled_rules",
                        lambda: _asyncval(list(_RULES) + [_WIN_RULE]))
    asyncio.run(engine.run_baseline("run-p2"))
    assert "NB-WIN-001" in {r.rule_id for r in written["results"]}
