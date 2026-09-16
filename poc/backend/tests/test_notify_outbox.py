"""Outbox: backoff curve + delivery state machine (ES mocked)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.notify import outbox  # noqa: E402


# ---- backoff -------------------------------------------------------------

def test_backoff_grows_and_caps():
    vals = [outbox._backoff_seconds(a) for a in range(1, 12)]
    # roughly increasing (jitter can wobble ±15%) and capped at the ceiling
    assert vals[0] < vals[5]
    assert all(v <= outbox._MAX_BACKOFF * 1.2 for v in vals)
    assert all(v >= 5.0 for v in vals)


# ---- _finish state machine ----------------------------------------------

class _FakeES:
    def __init__(self):
        self.written = None

    async def index(self, **kwargs):
        self.written = kwargs.get("document")


def _run_finish(src, **kw):
    fake = _FakeES()
    outbox.get_es = lambda: fake  # type: ignore[assignment]
    asyncio.run(outbox._finish("d1", src, **kw))
    return src


def test_finish_ok_marks_sent():
    src = {"attempts": 0, "status": "sending", "max_attempts": 6}
    _run_finish(src, ok=True)
    assert src["status"] == "sent"
    assert src["sent_at"]
    assert src["last_error"] == ""


def test_finish_retryable_increments_and_schedules():
    src = {"attempts": 0, "status": "sending", "max_attempts": 6}
    _run_finish(src, ok=False, error="boom", retryable=True)
    assert src["status"] == "failed"
    assert src["attempts"] == 1
    assert src["next_attempt_at"]
    assert src["last_error"] == "boom"


def test_finish_exhausted_retries_is_dead():
    src = {"attempts": 5, "status": "sending", "max_attempts": 6}
    _run_finish(src, ok=False, error="boom", retryable=True)
    assert src["attempts"] == 6
    assert src["status"] == "dead"


def test_finish_non_retryable_is_dead_immediately():
    src = {"attempts": 0, "status": "sending", "max_attempts": 6}
    _run_finish(src, ok=False, error="bad sign", retryable=False)
    assert src["status"] == "dead"
    assert src["attempts"] == 1


def test_finish_truncates_long_error():
    src = {"attempts": 0, "status": "sending", "max_attempts": 6}
    _run_finish(src, ok=False, error="x" * 999, retryable=True)
    assert len(src["last_error"]) == 400


# ---- egress masking (external Feishu) ------------------------------------

def test_egress_masks_ip_subject_in_cloud(monkeypatch):
    monkeypatch.setenv("RST_MASKING_MODE", "cloud")
    alert = {"severity": "high", "subject_field": "source.ip", "subject_value": "203.0.113.45"}
    safe = outbox.mask_alert_for_egress(alert)
    # subject value must not leave verbatim to the external channel
    assert safe["subject_value"] != "203.0.113.45"


def test_egress_passthrough_in_airgapped(monkeypatch):
    monkeypatch.setenv("RST_MASKING_MODE", "airgapped")
    alert = {"severity": "high", "subject_field": "user.name", "subject_value": "alice.wong"}
    safe = outbox.mask_alert_for_egress(alert)
    assert safe["subject_value"] == "alice.wong"


def test_deliver_treats_channel_validation_error_as_final(monkeypatch):
    """冷启动 2026-09-12：目标没填 webhook_url，channels.send 抛 ApiError，被当成
    「未知异常」按 retryable 循环，每 30 s 一条带 traceback 的 ERROR。
    配置错误不该重试，也不该是 ERROR。"""
    from backend.api_errors import ApiError

    calls = []

    async def fake_send(*_a, **_k):
        raise ApiError("webhook_url_required")

    async def fake_finish(doc_id, src, **kw):
        calls.append(kw)

    monkeypatch.setattr(outbox.channels, "send", fake_send)
    monkeypatch.setattr(outbox, "_finish", fake_finish)
    monkeypatch.setattr(outbox.secret_box, "decrypt", lambda _v: "")
    hit = {"_id": "d1", "_source": {"channel": "dingtalk", "body": {}, "attempts": 1}}
    asyncio.run(outbox._deliver(hit))
    assert calls and calls[0]["ok"] is False and calls[0]["retryable"] is False


def test_redacted_target_flags_ciphertext_this_key_cannot_open(monkeypatch):
    """高-6：重装后 .rst_secret_key 换了，ES 里的密文解不开；以前界面照样显示
    「已设置密钥」，只有投递失败才暴露。现在 secret_stale 明说。"""
    from backend.notify import config, secret_box

    monkeypatch.setattr(secret_box, "is_stale", lambda tok: tok == "old")
    good = config._redact_target({"id": "a", "channel": "feishu", "secret_enc": "new"})
    bad = config._redact_target({"id": "b", "channel": "feishu", "secret_enc": "old"})
    assert good["secret_set"] and not good["secret_stale"]
    assert bad["secret_set"] and bad["secret_stale"]
    assert "secret_enc" not in bad
