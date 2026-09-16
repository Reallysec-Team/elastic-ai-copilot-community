"""试用额度按部署所在时区切日，不按 UTC。

界面上写的是「每天 N 次」。按 UTC 切日的话，UTC+8 的客户额度在早上八点重置 ——
那不是他们的每天，而这是产品里唯一一处「一天」还归 UTC 管的地方。
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import license_state as ls, settings as gw_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setenv("RST_QUOTA_FILE", str(tmp_path / "quota.json"))
    ls._unactivated_calls.clear()
    yield
    ls._unactivated_calls.clear()


def test_the_quota_day_follows_rst_timezone(monkeypatch):
    """两个相隔 25 小时的时区，算出来的「今天」不可能是同一天 —— 不管此刻几点。

    直接拿 UTC 比是不行的：一天里有一大半时间，UTC 和 +08:00 的日期本来就相同，
    那样的用例只有半夜才会红。
    """
    monkeypatch.setenv("RST_TIMEZONE", "+14:00")
    east = ls._quota_day()
    monkeypatch.setenv("RST_TIMEZONE", "-11:00")
    west = ls._quota_day()
    assert east != west, f"额度的日界没跟着 RST_TIMEZONE 走：{east} == {west}"


def test_the_day_key_is_the_local_date(monkeypatch):
    monkeypatch.setenv("RST_TIMEZONE", "+14:00")
    assert ls._quota_day() == datetime.now(gw_settings.product_tz()).date().isoformat()


def test_unset_timezone_is_utc_as_before(monkeypatch):
    monkeypatch.delenv("RST_TIMEZONE", raising=False)
    assert ls._quota_day() == datetime.now(timezone.utc).date().isoformat()


def test_an_unreadable_timezone_falls_back_to_utc(monkeypatch):
    monkeypatch.setenv("RST_TIMEZONE", "Mars/Olympus")
    assert gw_settings.product_tz() is timezone.utc


def test_consume_and_refund_use_the_same_day_key(monkeypatch):
    """两边算的「今天」必须是同一个键，否则退还会退到别的日子上。"""
    monkeypatch.setenv("RST_TIMEZONE", "+08:00")
    monkeypatch.setattr(ls, "TRIAL_DAILY_LIMIT", 3)

    assert asyncio.run(ls.consume_unactivated_quota()) is True
    day = ls._quota_day()
    assert ls._unactivated_calls[day] == 1
    asyncio.run(ls.refund_unactivated_quota())
    assert ls._unactivated_calls[day] == 0


def test_the_quota_endpoint_reports_the_configured_timezone_string(monkeypatch):
    """回给界面的是操作者配的那个字符串，不是 `str(tzinfo)` 出来的 "UTC+08:00"。

    界面要把它显示给人看（「每天 00:00（+08:00）重置」）。回一个跟 .env 里写的对不上
    的写法，运维照着排查会先怀疑自己配错了。
    """
    from fastapi.testclient import TestClient

    from backend import main

    monkeypatch.setenv("RST_TIMEZONE", "+08:00")
    r = TestClient(main.app).get("/api/license/quota")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["timezone"] == "+08:00"
    assert body["reset_at_local"] == "00:00"
    # UTC 挂钟上的换日时刻跟着偏移走：东八区是前一天 16:00。
    assert body["reset_at_utc"] == "16:00"


def test_an_iana_zone_is_understood_too(monkeypatch):
    """`Asia/Shanghai` 这类名字以前只有报表调度器认，额度这边会退回 UTC。"""
    from datetime import datetime

    monkeypatch.setenv("RST_TIMEZONE", "Asia/Shanghai")
    tz = gw_settings.product_tz()
    assert tz is not timezone.utc
    assert ls._quota_day() == datetime.now(tz).date().isoformat()
    assert gw_settings.tz_name() == "Asia/Shanghai"


def test_the_report_schedule_falls_back_to_the_product_timezone(monkeypatch):
    """只设了 RST_TIMEZONE 的部署，日报也该按它切日 —— 以前它独立回落到 UTC，
    于是提示词和额度按东八区、日报却在北京时间早上八点出。"""
    from backend import report_scheduler as rs

    monkeypatch.setenv("RST_TIMEZONE", "+08:00")
    monkeypatch.delenv("RST_REPORT_TZ", raising=False)
    assert rs._report_tz() == gw_settings.product_tz()

    # 这一档自己的覆盖仍然优先。
    monkeypatch.setenv("RST_REPORT_TZ", "-05:00")
    assert rs._report_tz() != gw_settings.product_tz()
