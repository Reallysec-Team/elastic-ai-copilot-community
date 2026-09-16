"""/api/settings 的两道闸：脱敏模式的授权校验 + 审计 webhook 目的地。

这个端点能改脱敏模式、索引白名单和审计 sink —— 三样都是"关掉它就没人看得见了"
的东西，所以写入侧的校验比读取侧更重要。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import settings as gw_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("RST_AUDIT_WEBHOOK_ALLOWLIST", raising=False)


# ───────────────────────── masking_mode 授权 ─────────────────────────


def _allow(monkeypatch, modes):
    from backend import field_masking

    monkeypatch.setattr(field_masking, "available_modes", lambda: list(modes))


def test_airgapped_rejected_without_entitlement(monkeypatch):
    """airgapped = 完全不脱敏。不能靠 POST 一个配置就绕过 license。"""
    _allow(monkeypatch, ["cloud"])
    with pytest.raises(ValueError, match="airgapped"):
        gw_settings._validate_masking_mode({"masking_mode": "airgapped"})


def test_entitled_mode_accepted(monkeypatch):
    _allow(monkeypatch, ["cloud", "private", "airgapped"])
    gw_settings._validate_masking_mode({"masking_mode": "airgapped"})


def test_mode_check_is_case_and_space_tolerant(monkeypatch):
    _allow(monkeypatch, ["cloud"])
    with pytest.raises(ValueError):
        gw_settings._validate_masking_mode({"masking_mode": "  AirGapped "})


def test_absent_mode_is_not_a_change(monkeypatch):
    """没动这个键就不该校验 —— 否则改别的设置会被无关的 license 检查挡住。"""
    _allow(monkeypatch, ["cloud"])
    gw_settings._validate_masking_mode({"audit.enabled": True})
    gw_settings._validate_masking_mode({"masking_mode": ""})


# ───────────────────────── webhook 目的地 ─────────────────────────


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "169.254.169.254", "localhost"])
def test_loopback_and_metadata_refused(host):
    with pytest.raises(ValueError):
        gw_settings._check_webhook_host(host)


@pytest.mark.parametrize("host", ["10.0.0.5", "192.168.1.10", "siem.corp.example"])
def test_on_prem_targets_still_allowed(host):
    """内网 SIEM 就是装在 10/192.168 上的，默认不能把正常配置堵死。"""
    gw_settings._check_webhook_host(host)


def test_allowlist_when_set_is_exclusive(monkeypatch):
    monkeypatch.setenv("RST_AUDIT_WEBHOOK_ALLOWLIST", "siem.corp.example,*.internal")
    gw_settings._check_webhook_host("siem.corp.example")
    gw_settings._check_webhook_host("logs.internal")
    with pytest.raises(ValueError, match="ALLOWLIST"):
        gw_settings._check_webhook_host("evil.example.com")


def test_allowlist_overrides_the_default_block(monkeypatch):
    """显式允许了就照办 —— 有人真的把 SIEM 装在本机。"""
    monkeypatch.setenv("RST_AUDIT_WEBHOOK_ALLOWLIST", "127.0.0.1")
    gw_settings._check_webhook_host("127.0.0.1")


def test_full_url_validation_reaches_the_host_check():
    with pytest.raises(ValueError):
        gw_settings._validate_sink_urls({"audit.webhook_url": "http://169.254.169.254/latest"})


# ───────────────────────── 审计用的键名清单 ─────────────────────────


def test_changed_keys_flattens_and_drops_values():
    keys = gw_settings.changed_keys({"audit": {"enabled": True, "webhook_url": "http://x"}})
    assert keys == ["audit.enabled", "audit.webhook_url"]


def test_changed_keys_accepts_flat_form():
    assert gw_settings.changed_keys({"masking_mode": "cloud"}) == ["masking_mode"]
