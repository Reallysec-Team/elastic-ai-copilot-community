"""时间线里的 time 字段：模型写区间时不能把整条归档记录带走。

真事：一次调查跑完了、界面上结果好好的，归档却是空的。ES 拒收：

    document_parsing_exception ... [payload.timeline.time] of type [date]
    ... '2026-09-05T23:49:17Z ~ 23:50:05Z'

`.rst_copilot_analysis` 当初是靠动态映射长出来的，date 是从前几条推出来的；模型
一写区间，整条记录被拒，日志里只有一行 WARNING。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.investigate import _normalize, _split_timeline_time  # noqa: E402


def test_split_plain_timestamp():
    assert _split_timeline_time("2026-09-05T23:46:17Z") == ("2026-09-05T23:46:17Z", "")


def test_split_range_keeps_head_as_time_and_tail_as_text():
    ts, extra = _split_timeline_time("2026-09-05T23:49:17Z ~ 23:50:05Z")
    assert ts == "2026-09-05T23:49:17Z"
    assert extra == "23:50:05Z"


def test_split_non_date_leaves_time_empty():
    # 非日期字符串同样会被 date 字段拒掉 —— 空串不会。
    assert _split_timeline_time("刚刚") == ("", "刚刚")


def test_split_empty():
    assert _split_timeline_time("") == ("", "")
    assert _split_timeline_time(None) == ("", "")


def test_normalize_moves_the_range_into_the_event_text():
    out = _normalize(
        {"timeline": [{"time": "2026-09-05T23:49:17Z ~ 23:50:05Z", "event": "执行 id 与 uname -a"}]},
        0,
    )
    item = out["timeline"][0]
    assert item["time"] == "2026-09-05T23:49:17Z"
    # 区间的后半截没丢，只是挪进了事件描述
    assert "23:50:05Z" in item["event"]
    assert "执行 id 与 uname -a" in item["event"]
