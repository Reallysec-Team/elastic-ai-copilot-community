"""AI summary gating + masked payload (no live LLM)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.alerts import summarize  # noqa: E402


def test_enabled_by_default(monkeypatch):
    monkeypatch.delenv("RST_ALERT_SUMMARY", raising=False)
    assert summarize._enabled() is True


def test_disabled_by_env(monkeypatch):
    for v in ("0", "false", "no", "off"):
        monkeypatch.setenv("RST_ALERT_SUMMARY", v)
        assert summarize._enabled() is False


def test_min_severity_floor(monkeypatch):
    monkeypatch.setenv("RST_ALERT_SUMMARY_MIN_SEVERITY", "high")
    assert summarize._min_severity_ok("critical") is True
    assert summarize._min_severity_ok("high") is True
    assert summarize._min_severity_ok("medium") is False
    assert summarize._min_severity_ok("info") is False


def test_min_severity_default_all(monkeypatch):
    monkeypatch.delenv("RST_ALERT_SUMMARY_MIN_SEVERITY", raising=False)
    assert summarize._min_severity_ok("info") is True


def test_payload_masks_ip_in_cloud(monkeypatch):
    monkeypatch.setenv("RST_MASKING_MODE", "cloud")
    alert = {"rule_name": "brute force", "severity": "high",
             "subject_field": "source.ip", "subject_value": "45.9.148.22",
             "raw": {"source.ip": "45.9.148.22", "message": "many fails"}}
    p = summarize._payload(alert)
    # the masked payload must not carry the raw last octet to the LLM
    assert "45.9.148.22" not in str(p)
    assert p["rule_name"] == "brute force"


def test_payload_passthrough_airgapped(monkeypatch):
    monkeypatch.setenv("RST_MASKING_MODE", "airgapped")
    alert = {"rule_name": "x", "severity": "high", "subject_field": "user.name",
             "subject_value": "alice", "raw": {"user.name": "alice"}}
    p = summarize._payload(alert)
    assert "alice" in str(p)
