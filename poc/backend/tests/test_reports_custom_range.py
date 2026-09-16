"""运营报告的自定义时间区间。

三张周期卡是快捷入口；事后复盘要的是「昨晚 21:47 到 22:15」。这里守的是那些
「看上去生成成功了、其实报的是另一段时间」的情形 —— 报告会被投递出去、会归档，
标签写错比生成失败更难发现。
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import reports  # noqa: E402


class _FakeES:
    """report_agg 那几个聚合都只读 ES，这里让它们拿到空结果即可 —— 这个测试关心的
    是窗口和标签怎么算出来的，不是聚合本身。"""

    async def search(self, *a, **kw):
        return type("R", (), {"body": {"hits": {"total": {"value": 0}, "hits": []},
                                       "aggregations": {}}})()

    async def count(self, *a, **kw):
        return type("R", (), {"body": {"count": 0}})()


@pytest.fixture(autouse=True)
def _stub_es(monkeypatch):
    monkeypatch.setattr(reports, "get_es", lambda: _FakeES())


async def _gen(**kw):
    return await reports.generate(**kw)


@pytest.mark.asyncio
async def test_custom_window_is_used_verbatim():
    start = datetime(2026, 9, 5, 21, 47, tzinfo=timezone.utc)
    end = datetime(2026, 9, 5, 22, 15, tzinfo=timezone.utc)
    r = await _gen(period="daily", start=start, end=end)
    assert r["start_at"].startswith("2026-09-05T21:47")
    assert r["end_at"].startswith("2026-09-05T22:15")


@pytest.mark.asyncio
async def test_custom_window_relabels_itself():
    """沿用「过去 24 小时」会让一份九月三号两小时的报告在归档和投递里自称是
    过去 24 小时的 —— 那行字会一路传到飞书卡片和邮件标题上。"""
    start = datetime(2026, 9, 5, 21, 47, tzinfo=timezone.utc)
    end = datetime(2026, 9, 5, 22, 15, tzinfo=timezone.utc)
    r = await _gen(period="daily", start=start, end=end)
    assert "过去 24 小时" not in r["label"]
    assert "2026-09-05 21:47" in r["label"] and "2026-09-05 22:15" in r["label"]


@pytest.mark.asyncio
@pytest.mark.parametrize("span,expected", [
    (timedelta(hours=2), "daily"),      # 两小时 → 细粒度分桶
    (timedelta(days=5), "weekly"),
    (timedelta(days=25), "monthly"),    # 跨月按分钟分桶，出来的是一张画不出的图
])
async def test_bucket_granularity_follows_the_span_not_the_period(span, expected):
    end = datetime(2026, 9, 6, tzinfo=timezone.utc)
    r = await _gen(period="daily", start=end - span, end=end)
    assert r["period"] == expected


@pytest.mark.asyncio
async def test_reversed_window_is_refused():
    end = datetime(2026, 9, 5, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="早于"):
        await _gen(period="daily", start=end + timedelta(days=1), end=end)


@pytest.mark.asyncio
async def test_without_start_the_period_still_decides_the_window():
    """老路径不能被这次改动动到：不给 start，就还是「period 长度的窗口，到 end」。"""
    end = datetime(2026, 9, 6, tzinfo=timezone.utc)
    r = await _gen(period="weekly", end=end)
    assert r["start_at"].startswith("2026-08-30")
    assert r["label"] == "过去 7 天"
