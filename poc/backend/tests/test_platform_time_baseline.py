"""时间基线体检：把「查不到数据」这个哑谜翻译成一句话。

时间错了的现象是**查不到数据，而且不报错** —— 客户问「今天下午登录失败最多的 IP」
拿到零条，然后去排查一个不存在的故障。这条检查的全部价值就是分清三种成因，因为
它们的修法完全不同：整体领先（采集端时区）、单机落后（NTP）、采集延迟（不是错误）。
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.platform_ops import checks  # noqa: E402


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _stub(monkeypatch, baseline: dict, streams=("logs-a",)):
    async def fake_streams():
        return [{"name": n} for n in streams], None

    async def fake_baseline(index, host_field="host.name"):
        return baseline, None

    monkeypatch.setattr(checks.probe, "data_streams", fake_streams)
    monkeypatch.setattr(checks.probe, "time_baseline", fake_baseline)


@pytest.fixture
def now():
    return datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_healthy_cluster_says_so(monkeypatch, now):
    _stub(monkeypatch, {
        "newest": _iso(now - timedelta(minutes=2)),
        "oldest": _iso(now - timedelta(days=7)),
        "hosts": [], "lag_ms": {},
    })
    r = await checks.check_time_baseline(whitelist_patterns=[])
    assert r["verdict"] == checks.OK
    assert "一致" in r["summary"]


@pytest.mark.asyncio
async def test_future_logs_are_a_failure(monkeypatch, now):
    """+8 小时的「未来日志」= 采集端把本地时间当 UTC 写了。这是最常见的一种，
    也是最难自己看出来的 —— 界面上只表现为「今天的数据查不到」。"""
    _stub(monkeypatch, {
        "newest": _iso(now + timedelta(hours=8)),
        "oldest": _iso(now - timedelta(days=1)),
        "hosts": [], "lag_ms": {},
    })
    r = await checks.check_time_baseline(whitelist_patterns=[])
    assert r["verdict"] == checks.FAIL
    assert "未来" in r["summary"]
    # 没有主机维度（或全体一起偏）时，指向采集端时区
    # 处置要指向采集端，并说清楚为什么产品不代改
    assert "timezone" in r["advice"] and "reindex" in r["advice"]


@pytest.mark.asyncio
async def test_small_ahead_is_a_warning_not_a_failure(monkeypatch, now):
    """几分钟的领先多半是时钟微漂，不值得报红。"""
    _stub(monkeypatch, {
        "newest": _iso(now + timedelta(minutes=10)),
        "oldest": _iso(now - timedelta(days=1)),
        "hosts": [], "lag_ms": {},
    })
    r = await checks.check_time_baseline(whitelist_patterns=[])
    assert r["verdict"] == checks.WARN


@pytest.mark.asyncio
async def test_a_host_ahead_of_now_is_flagged_by_name(monkeypatch, now):
    """单机时钟快 —— 唯一能确诊的按主机信号。

    一台机器快，整条流的 max 也跟着领先（两个信号是耦合的），所以区分成因靠的是
    **范围**：只有个别主机偏 = 那几台的时钟；全体偏 = 采集端时区。"""
    _stub(monkeypatch, {
        "newest": _iso(now + timedelta(minutes=20)),
        "oldest": _iso(now - timedelta(days=1)),
        "hosts": [
            {"host": "web-01", "newest": _iso(now - timedelta(minutes=1))},
            {"host": "db-07", "newest": _iso(now + timedelta(minutes=20))},
        ],
        "lag_ms": {},
    })
    r = await checks.check_time_baseline(whitelist_patterns=[])
    assert r["verdict"] == checks.WARN
    assert "db-07" in r["summary"]
    assert "web-01" not in r["summary"]
    assert "NTP" in r["advice"] and "不是采集端时区" in r["advice"]


@pytest.mark.asyncio
async def test_a_quiet_host_is_not_a_clock_problem(monkeypatch, now):
    """一台机器安静几十小时可能只是它没什么日志，而「采集停了」由
    check_ingest_freshness 管。拿落后去猜时钟偏移，会把每台安静的主机都报成
    故障 —— 真跑演示数据时一次误报了 5 台，这条测试就是为它写的。"""
    _stub(monkeypatch, {
        "newest": _iso(now - timedelta(minutes=1)),
        "oldest": _iso(now - timedelta(days=7)),
        "hosts": [
            {"host": "web-01", "newest": _iso(now - timedelta(minutes=1))},
            {"host": "db-07", "newest": _iso(now - timedelta(hours=64))},
        ],
        "lag_ms": {},
    })
    r = await checks.check_time_baseline(whitelist_patterns=[])
    assert r["verdict"] == checks.OK
    assert r["detail"]["skewed_hosts"] == []


@pytest.mark.asyncio
async def test_ingest_lag_is_reported_without_failing(monkeypatch, now):
    """采集延迟不是故障，但「最近 1 分钟查不到」要靠它解释，否则用户会去查一个
    不存在的故障。"""
    _stub(monkeypatch, {
        "newest": _iso(now - timedelta(minutes=1)),
        "oldest": _iso(now - timedelta(days=1)),
        "hosts": [],
        "lag_ms": {"50.0": 300_000, "95.0": 900_000},   # 中位 5 分钟
    })
    r = await checks.check_time_baseline(whitelist_patterns=[])
    assert r["verdict"] == checks.OK, "延迟本身不该判失败"
    assert "采集延迟" in r["summary"]
    assert r["detail"]["ingest_lag_seconds_p50"] == 300.0


@pytest.mark.asyncio
async def test_missing_lag_field_is_not_an_error(monkeypatch, now):
    """event.ingested 要 ingest pipeline 才有，没有是常态。"""
    _stub(monkeypatch, {
        "newest": _iso(now - timedelta(minutes=1)),
        "oldest": _iso(now - timedelta(days=1)),
        "hosts": [], "lag_ms": {"50.0": None},
    })
    r = await checks.check_time_baseline(whitelist_patterns=[])
    assert r["verdict"] == checks.OK
    assert r["detail"]["ingest_lag_seconds_p50"] is None


@pytest.mark.asyncio
async def test_probe_failure_degrades_to_unknown(monkeypatch):
    """一个索引读不到不该把整份体检打成失败 —— 这是这套检查的既定约定。"""
    async def fake_streams():
        return [{"name": "logs-a"}], None

    async def boom(index, host_field="host.name"):
        return None, "权限不足"

    monkeypatch.setattr(checks.probe, "data_streams", fake_streams)
    monkeypatch.setattr(checks.probe, "time_baseline", boom)
    r = await checks.check_time_baseline(whitelist_patterns=[])
    assert r["verdict"] == checks.UNKNOWN


@pytest.mark.asyncio
async def test_registered_in_the_report(monkeypatch, now):
    """加了检查函数却忘了挂进报告，是这套东西最容易犯的错。"""
    assert "check_time_baseline" in checks._CHECK_FNS
    assert checks._TITLES["check_time_baseline"] == "时间基线"
