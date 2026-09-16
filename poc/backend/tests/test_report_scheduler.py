"""Report scheduler — boundary keys, period parsing, multi-replica claim, and
the retry-on-failure rule. No ES/LLM (claim + generate are monkeypatched)."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import report_scheduler as rs  # noqa: E402


def test_boundary_keys():
    dt = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)  # Wed, ISO 2026-W27
    assert rs._boundary_key("daily", dt) == "2026-07-01"
    assert rs._boundary_key("monthly", dt) == "2026-07"
    assert rs._boundary_key("weekly", dt) == dt.strftime("%G-W%V")


def test_enabled_periods(monkeypatch):
    monkeypatch.setenv("RST_REPORT_SCHEDULE", "daily, monthly , bogus")
    assert rs._enabled_periods() == ["daily", "monthly"]
    monkeypatch.delenv("RST_REPORT_SCHEDULE", raising=False)
    assert rs._enabled_periods() == []


def test_fire_skips_when_claim_lost(monkeypatch):
    """Multi-replica dedup: a lost claim → done (no re-fire), generation skipped."""
    monkeypatch.setenv("RST_REPORT_PERSIST", "1")
    called = {"gen": False}

    async def _claim_lost(_p, _k):
        return None  # 没拿到就是 None（以前这里三态挤在 str | bool 里）

    async def _gen(*_a, **_k):
        called["gen"] = True
        return {}

    monkeypatch.setattr(rs, "_claim", _claim_lost)
    monkeypatch.setattr(rs.reports, "generate", _gen)

    assert asyncio.run(rs._fire("daily", "2026-07-01")) is True
    assert called["gen"] is False


def test_fire_returns_false_on_generate_error(monkeypatch):
    """A transient generate failure → False so the loop retries next tick."""
    monkeypatch.setenv("RST_REPORT_PERSIST", "0")  # no persistence → no claim

    async def _boom(*_a, **_k):
        raise RuntimeError("es down")

    monkeypatch.setattr(rs.reports, "generate", _boom)
    assert asyncio.run(rs._fire("daily", "2026-07-01")) is False


# ── boundary timezone ───────────────────────────────────────────────────────

def test_boundary_key_follows_the_configured_timezone(monkeypatch):
    """With UTC boundaries the daily 巡检 fires at 08:00 Beijing time and is
    filed under the wrong local date."""
    dt = datetime(2026, 7, 1, 17, 30, tzinfo=timezone.utc)  # 2026-07-02 01:30 +08
    assert rs._boundary_key("daily", dt) == "2026-07-01"

    monkeypatch.setenv("RST_REPORT_TZ", "+08:00")
    assert rs._boundary_key("daily", dt) == "2026-07-02"
    assert rs._boundary_key("monthly", dt) == "2026-07"


def test_an_unparseable_timezone_falls_back_to_utc(monkeypatch):
    monkeypatch.setenv("RST_REPORT_TZ", "Mars/Olympus")
    dt = datetime(2026, 7, 1, 17, 30, tzinfo=timezone.utc)
    assert rs._boundary_key("daily", dt) == "2026-07-01"


# ── catch-up after downtime ─────────────────────────────────────────────────

def _now(y, m, d, h=0):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


def test_nothing_pending_when_the_boundary_already_fired():
    assert rs._pending_boundaries("daily", "2026-07-22", _now(2026, 7, 22, 12)) == []


def test_a_cold_start_does_not_invent_a_backlog():
    """No archive → no idea how far the gap goes; only the current boundary."""
    pending = rs._pending_boundaries("daily", None, _now(2026, 7, 22, 12))
    assert [k for k, _ in pending] == ["2026-07-22"]


def test_boundaries_missed_during_downtime_are_backfilled_oldest_first():
    """The confirmed bug: down Sat→Wed produced ONE report on restart and the
    three missed days were gone, with nothing anywhere saying so."""
    pending = rs._pending_boundaries("daily", "2026-07-18", _now(2026, 7, 22, 12))
    assert [k for k, _ in pending] == ["2026-07-19", "2026-07-20", "2026-07-21", "2026-07-22"]


def test_a_backfilled_report_covers_its_own_period_not_the_restart_moment():
    """A report filed under 07-20 must not contain 07-22's data."""
    pending = rs._pending_boundaries("daily", "2026-07-19", _now(2026, 7, 22, 12))
    by_key = dict(pending)
    # window_end = the boundary's own start; generate() looks back one period
    # from there, which is exactly what the on-time fire would have covered.
    assert by_key["2026-07-20"] == rs._boundary_start("daily", _now(2026, 7, 20))
    assert by_key["2026-07-21"] == rs._boundary_start("daily", _now(2026, 7, 21))


def test_a_long_outage_is_capped_and_says_so(monkeypatch, caplog):
    monkeypatch.setenv("RST_REPORT_CATCHUP_MAX", "2")
    with caplog.at_level("WARNING"):
        pending = rs._pending_boundaries("daily", "2026-01-01", _now(2026, 7, 22, 12))
    assert [k for k, _ in pending] == ["2026-07-20", "2026-07-21", "2026-07-22"]
    assert "report_catchup_truncated" in caplog.text, "a silent cap reads as full coverage"


def test_catchup_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("RST_REPORT_CATCHUP_MAX", "0")
    pending = rs._pending_boundaries("daily", "2026-07-18", _now(2026, 7, 22, 12))
    assert [k for k, _ in pending] == ["2026-07-22"]


def test_weekly_and_monthly_backfill_on_their_own_calendar():
    weekly = rs._pending_boundaries("weekly", "2026-W27", _now(2026, 7, 22, 12))
    assert [k for k, _ in weekly] == ["2026-W28", "2026-W29", "2026-W30"]
    monthly = rs._pending_boundaries("monthly", "2026-04", _now(2026, 7, 22, 12))
    assert [k for k, _ in monthly] == ["2026-05", "2026-06", "2026-07"]


def test_a_backfill_carries_its_window_into_generate(monkeypatch):
    """_fire must pass the historical end through, and must NOT staple today's
    triage onto a past boundary."""
    monkeypatch.setenv("RST_REPORT_PERSIST", "0")
    seen = {}

    async def _gen(period, *, include_health=False, end=None):
        seen["end"] = end
        return {"generated_at": "t", "start_at": "s", "end_at": "e", "markdown": ""}

    async def _sec(_p):  # pragma: no cover — must not be called on a backfill
        raise AssertionError("triage_alerts only looks back from NOW")

    monkeypatch.setattr(rs.reports, "generate", _gen)
    monkeypatch.setattr(rs, "_security_section", _sec)
    monkeypatch.setattr(rs, "_webhook", lambda: None)

    end = _now(2026, 7, 20)
    assert asyncio.run(rs._fire("daily", "2026-07-20", end)) is True
    assert seen["end"] == end


# ── 失败清理不能删掉别人的东西 ─────────────────────────────────────────────


class _FakeES:
    """够用的 get / delete / index 替身，记下删了什么。"""

    def __init__(self, doc: dict | None):
        self.doc = doc
        self.deleted: list[str] = []

    class _Body:
        def __init__(self, body):
            self.body = body

    async def get(self, index, id):  # noqa: A002
        if self.doc is None:
            raise RuntimeError("not found")
        return self._Body({"_source": self.doc, "_seq_no": 7, "_primary_term": 1})

    async def delete(self, index, id, **kw):  # noqa: A002
        self.deleted.append(id)
        return self._Body({"result": "deleted"})


def _release_against(monkeypatch, doc, claimed_at):
    es = _FakeES(doc)
    monkeypatch.setattr(rs, "get_es", lambda: es)
    asyncio.run(rs._release("daily", "2026-07-01", claimed_at))
    return es


def test_release_removes_our_own_pending_placeholder(monkeypatch):
    es = _release_against(
        monkeypatch,
        {"status": "pending", "claimed_at": "2026-07-01T00:00:00+00:00"},
        "2026-07-01T00:00:00+00:00",
    )
    assert es.deleted == ["daily-2026-07-01"]


def test_release_leaves_a_finished_report_alone(monkeypatch):
    """租约超时被接管、那边已经把完整报告写进去了 —— 我们这次的失败清理不能删它。"""
    es = _release_against(
        monkeypatch,
        {"status": "complete", "markdown": "别人的报告"},
        "2026-07-01T00:00:00+00:00",
    )
    assert es.deleted == []


def test_release_leaves_someone_elses_live_claim_alone(monkeypatch):
    es = _release_against(
        monkeypatch,
        {"status": "pending", "claimed_at": "2026-07-01T00:30:00+00:00"},  # 别人的戳
        "2026-07-01T00:00:00+00:00",
    )
    assert es.deleted == []


def test_release_does_nothing_when_we_never_held_a_claim(monkeypatch):
    """claim 那一步 ES 就报错、我们是 fail open 发出去的 —— 没有占位文档是我们的。"""
    es = _release_against(monkeypatch, {"status": "pending"}, None)
    assert es.deleted == []


def test_a_failed_generate_releases_the_claim_it_took(monkeypatch):
    """端到端：claim 拿到了戳，generate 炸了，释放的是自己那一个。"""
    monkeypatch.setenv("RST_REPORT_PERSIST", "1")
    released: list = []

    async def _claim_ok(_p, _k):
        return "2026-07-01T00:00:00+00:00"

    async def _boom(*_a, **_k):
        raise RuntimeError("es down")

    async def _rel(period, key, claimed_at):
        released.append((period, key, claimed_at))

    monkeypatch.setattr(rs, "_claim", _claim_ok)
    monkeypatch.setattr(rs, "_release", _rel)
    monkeypatch.setattr(rs.reports, "generate", _boom)

    assert asyncio.run(rs._fire("daily", "2026-07-01")) is False
    assert released == [("daily", "2026-07-01", "2026-07-01T00:00:00+00:00")]


# ── 配置改了不用重启 ────────────────────────────────────────────────────────


def test_the_schedule_is_re_read_every_tick(monkeypatch):
    """把 RST_REPORT_SCHEDULE 配上之后不用重启网关 —— 告警接入一直是这个行为。

    另外，新冒出来的周期必须先从归档认位（seed），否则 `_last_fired` 是空的、
    被当成冷启动，会把这一档已经归档过的当期报告再发一遍。
    """
    monkeypatch.setattr(rs, "_check_interval", lambda: 0.01)
    monkeypatch.delenv("RST_REPORT_SCHEDULE", raising=False)
    rs._last_fired.clear()

    seeded: list[list[str]] = []
    fired: list[str] = []

    async def _seed(periods):
        seeded.append(list(periods))

    async def _fire(period, key, window_end=None):
        fired.append(period)
        return True

    monkeypatch.setattr(rs, "_seed_last_fired", _seed)
    monkeypatch.setattr(rs, "_fire", _fire)

    async def run():
        task = asyncio.create_task(rs._loop())
        await asyncio.sleep(0.05)
        assert fired == [], "还没配周期就发了"
        monkeypatch.setenv("RST_REPORT_SCHEDULE", "daily")
        await asyncio.sleep(0.08)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
    assert "daily" in fired, "配上之后应当无需重启就开始跑"
    assert seeded and seeded[0] == ["daily"], f"新周期必须先 seed，实际 {seeded}"


def test_start_runs_even_with_nothing_scheduled(monkeypatch):
    """空转到有周期为止 —— 和 alerts.ingest.start() 同一套。"""
    monkeypatch.delenv("RST_REPORT_SCHEDULE", raising=False)

    async def run():
        async def _noop():
            await asyncio.sleep(0)

        monkeypatch.setattr(rs, "_loop", _noop)
        rs.start()
        assert rs._task is not None
        await rs.stop()

    asyncio.run(run())


def test_claim_hands_back_a_stamp_even_when_es_is_down(monkeypatch):
    """ES 报错时 fail open（照样发），返回的是本来要写的那个戳。

    以前这一支返回 True，调用方得 `isinstance` 才能用对；而 `_release` 在这种
    情况下必须什么都不删 —— 占位文档大概率根本没落地。
    """
    class _DeadES:
        async def index(self, **kw):
            raise RuntimeError("es down")

    monkeypatch.setenv("RST_REPORT_PERSIST", "1")
    monkeypatch.setattr(rs, "get_es", lambda: _DeadES())

    stamp = asyncio.run(rs._claim("daily", "2026-07-01"))
    assert isinstance(stamp, str) and stamp, "fail open 也要给出戳"

    # 拿着这个戳去释放：文档不存在 → 什么都不删，也不抛。
    es = _FakeES(None)
    monkeypatch.setattr(rs, "get_es", lambda: es)
    asyncio.run(rs._release("daily", "2026-07-01", stamp))
    assert es.deleted == []
