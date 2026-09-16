import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import report_render as rr  # noqa: E402


def test_bucket_interval_per_period():
    assert rr.bucket_interval("daily") == "1h"
    assert rr.bucket_interval("weekly") == "1d"
    assert rr.bucket_interval("monthly") == "1d"
    assert rr.bucket_interval("bogus") == "1d"


def test_sparkline_empty_is_blank():
    assert rr.sparkline([]) == ""


def test_sparkline_length_matches_buckets():
    assert len(rr.sparkline([0, 1, 2, 3, 4, 5])) == 6


def test_sparkline_all_zero_is_floor():
    assert rr.sparkline([0, 0, 0]) == "▁▁▁"


def test_sparkline_max_maps_to_top_block():
    out = rr.sparkline([0, 10])
    assert out[0] == "▁"
    assert out[1] == "█"
