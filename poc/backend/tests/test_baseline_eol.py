"""EOL 判定纯函数单测（TDD）—— HB-SYS-001 自动判定核心。

判定确定性：所有日期比对吃注入的 today: date，纯函数内不读 now。
判定只查本地 eol-catalog（这里用 fake lookup 注入），绝不触外网。

verdict 矩阵:
  os_version 无结果行            → error（拿不到 OS，判不了）
  发行版名映射不到 slug          → manual_review（未知发行版，交人工）
  slug 已知但 eol-catalog 无该 cycle → error（缓存缺项，需同步）
  catalog eol 日期 已过 today     → fail
  catalog eol 日期 未过 / 当天     → pass
  catalog eol == "false"（仍支持） → pass
  catalog eol == "true"（已 EOL）  → fail
  catalog eol 不可解析            → error
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.baseline import eol  # noqa: E402
from backend.baseline.schema import (  # noqa: E402
    VERDICT_ERROR,
    VERDICT_FAIL,
    VERDICT_MANUAL,
    VERDICT_PASS,
)

_TODAY = date(2026, 7, 4)


# ---- extract_os：从结果行取 (name, version) ----
def test_extract_os_reads_first_row():
    rows = [{"name": "CentOS Linux", "version": "7.9.2009", "platform": "rhel"}]
    assert eol.extract_os(rows) == ("CentOS Linux", "7.9.2009")


def test_extract_os_empty_rows_is_none():
    assert eol.extract_os([]) is None


def test_extract_os_missing_name_is_none():
    assert eol.extract_os([{"version": "7"}]) is None


# ---- to_slug：发行版名 → endoflife 产品 slug ----
def test_to_slug_common_distros():
    assert eol.to_slug("CentOS Linux") == "centos"
    assert eol.to_slug("Ubuntu") == "ubuntu"
    assert eol.to_slug("Debian GNU/Linux") == "debian"
    assert eol.to_slug("Red Hat Enterprise Linux") == "rhel"
    assert eol.to_slug("AlmaLinux") == "almalinux"
    assert eol.to_slug("Rocky Linux") == "rocky"


def test_to_slug_case_insensitive():
    assert eol.to_slug("ubuntu") == "ubuntu"
    assert eol.to_slug("  DEBIAN  ") == "debian"


def test_to_slug_falls_back_to_platform():
    assert eol.to_slug("", platform="ubuntu") == "ubuntu"


def test_to_slug_unknown_is_none():
    assert eol.to_slug("TempleOS") is None
    assert eol.to_slug("") is None


# ---- to_cycle：版本号 → endoflife cycle ----
def test_to_cycle_major_only_for_rhel_family():
    assert eol.to_cycle("centos", "7.9.2009") == "7"
    assert eol.to_cycle("debian", "12") == "12"
    assert eol.to_cycle("rhel", "8.10") == "8"


def test_to_cycle_major_minor_for_ubuntu():
    assert eol.to_cycle("ubuntu", "22.04.3 LTS") == "22.04"
    assert eol.to_cycle("ubuntu", "20.04") == "20.04"


def test_to_cycle_unparseable_is_none():
    assert eol.to_cycle("centos", "") is None
    assert eol.to_cycle("centos", "unknown") is None


# ---- compare_eol：EOL 原始值 + today → verdict ----
def test_compare_eol_past_date_is_fail():
    assert eol.compare_eol("2024-06-30", _TODAY) == VERDICT_FAIL


def test_compare_eol_future_date_is_pass():
    assert eol.compare_eol("2029-05-31", _TODAY) == VERDICT_PASS


def test_compare_eol_boundary_today_is_pass():
    # EOL 当天仍为支持最后一日 → pass；次日才 fail
    assert eol.compare_eol("2026-07-04", _TODAY) == VERDICT_PASS
    assert eol.compare_eol("2026-07-03", _TODAY) == VERDICT_FAIL


def test_compare_eol_bool_false_is_pass():
    assert eol.compare_eol("false", _TODAY) == VERDICT_PASS


def test_compare_eol_bool_true_is_fail():
    assert eol.compare_eol("true", _TODAY) == VERDICT_FAIL


def test_compare_eol_unparseable_is_error():
    assert eol.compare_eol("someday", _TODAY) == VERDICT_ERROR
    assert eol.compare_eol("", _TODAY) == VERDICT_ERROR
    assert eol.compare_eol(None, _TODAY) == VERDICT_ERROR


# ---- decide：整合 slug/cycle/entry → (verdict, actual) 纯函数 ----
def test_decide_found_entry_pass():
    entry = {"eol_raw": "2029-05-31"}
    verdict, actual = eol.decide("CentOS Linux", "7.9.2009", "centos", "7", entry, _TODAY)
    assert verdict == VERDICT_PASS
    assert "centos" in actual and "7" in actual


def test_decide_found_entry_fail():
    entry = {"eol_raw": "2024-06-30"}
    verdict, _ = eol.decide("CentOS Linux", "7.9.2009", "centos", "7", entry, _TODAY)
    assert verdict == VERDICT_FAIL


def test_decide_catalog_miss_is_error():
    verdict, actual = eol.decide("CentOS Linux", "7", "centos", "7", None, _TODAY)
    assert verdict == VERDICT_ERROR
    assert "centos:7" in actual  # 提示缺哪条


# ---- judge_eol：async 编排，注入 fake lookup + today ----
def _run(coro):
    return asyncio.run(coro)


def test_judge_eol_empty_rows_is_error():
    async def _lookup(p, c):
        return None
    verdict, actual = _run(eol.judge_eol([], today=_TODAY, lookup=_lookup))
    assert verdict == VERDICT_ERROR


def test_judge_eol_unknown_distro_is_manual():
    async def _lookup(p, c):
        raise AssertionError("未知发行版不该查 catalog")
    rows = [{"name": "TempleOS", "version": "1.0"}]
    verdict, actual = _run(eol.judge_eol(rows, today=_TODAY, lookup=_lookup))
    assert verdict == VERDICT_MANUAL


def test_judge_eol_eol_host_is_fail():
    async def _lookup(product, cycle):
        assert (product, cycle) == ("centos", "7")
        return {"eol_raw": "2024-06-30"}
    rows = [{"name": "CentOS Linux", "version": "7.9.2009"}]
    verdict, _ = _run(eol.judge_eol(rows, today=_TODAY, lookup=_lookup))
    assert verdict == VERDICT_FAIL


def test_judge_eol_supported_host_is_pass():
    async def _lookup(product, cycle):
        return {"eol_raw": "2029-05-31"}
    rows = [{"name": "CentOS Linux", "version": "8.5.2111"}]
    verdict, _ = _run(eol.judge_eol(rows, today=_TODAY, lookup=_lookup))
    assert verdict == VERDICT_PASS


def test_judge_eol_catalog_miss_is_error():
    async def _lookup(product, cycle):
        return None
    rows = [{"name": "CentOS Linux", "version": "6.10"}]
    verdict, _ = _run(eol.judge_eol(rows, today=_TODAY, lookup=_lookup))
    assert verdict == VERDICT_ERROR
