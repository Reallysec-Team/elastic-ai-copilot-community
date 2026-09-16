"""审计外发：有界重试，以及转发失败在记录本体上留痕。

需要先说清楚这里**不**保证什么：审计事件本身不会因为转发失败而丢 —— ES 审计索引
才是记录本体，syslog / webhook 是额外的投递目标（见 audit_sinks 模块注释）。所以
这几条测试盯的是「转发这一次」的可靠性和可观测性，不是事件的持久化。
"""
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent  # .../poc
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

import pytest  # noqa: E402

from backend import audit, audit_sinks  # noqa: E402


class _Resp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _Client:
    """httpx.AsyncClient 的替身：按脚本依次返回状态码或抛异常。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        self.calls += 1
        item = self.script.pop(0) if self.script else self.script_default
        if isinstance(item, BaseException):
            raise item
        return _Resp(item)


@pytest.fixture
def no_sleep(monkeypatch):
    """退避不真睡，否则每条用例要 2 秒。"""
    async def instant(_s):
        return None

    monkeypatch.setattr(audit_sinks.asyncio, "sleep", instant)


def _wire(monkeypatch, script):
    client = _Client(script)
    monkeypatch.setattr(audit_sinks.httpx, "AsyncClient", lambda **kw: client)
    return client


@pytest.mark.anyio
async def test_transient_failure_is_retried_then_succeeds(monkeypatch, no_sleep):
    client = _wire(monkeypatch, [500, 503, 200])
    sink = audit_sinks.WebhookSink("https://siem.example/hook")
    assert await sink.write({"action": "x"}) is True
    assert client.calls == 3


@pytest.mark.anyio
async def test_gives_up_after_the_bound(monkeypatch, no_sleep):
    client = _wire(monkeypatch, [500, 500, 500])
    sink = audit_sinks.WebhookSink("https://siem.example/hook")
    assert await sink.write({"action": "x"}) is False
    assert client.calls == audit_sinks._WEBHOOK_ATTEMPTS


@pytest.mark.anyio
async def test_network_errors_are_retried(monkeypatch, no_sleep):
    client = _wire(monkeypatch, [OSError("connection reset"), 200])
    sink = audit_sinks.WebhookSink("https://siem.example/hook")
    assert await sink.write({"action": "x"}) is True
    assert client.calls == 2


@pytest.mark.anyio
async def test_client_errors_are_not_retried(monkeypatch, no_sleep):
    """401 / 404 是配置错，重试只是把同一个错误多发两遍。"""
    client = _wire(monkeypatch, [401, 200, 200])
    sink = audit_sinks.WebhookSink("https://siem.example/hook")
    assert await sink.write({"action": "x"}) is False
    assert client.calls == 1


@pytest.mark.anyio
async def test_429_is_retried(monkeypatch, no_sleep):
    """429 是 4xx 里唯一的例外：它明确在说「等一下再来」。"""
    client = _wire(monkeypatch, [429, 200])
    sink = audit_sinks.WebhookSink("https://siem.example/hook")
    assert await sink.write({"action": "x"}) is True
    assert client.calls == 2


# ── 记录本体上的留痕 ────────────────────────────────────────────────────

class _FailingSink(audit_sinks.Sink):
    kind = "webhook"

    async def write(self, event):
        return False


class _OkSink(audit_sinks.Sink):
    kind = "syslog"

    async def write(self, event):
        return True


class _ES:
    def __init__(self):
        self.updates = []

    async def index(self, **kw):
        return {"_id": "abc123"}

    async def update(self, index=None, id=None, doc=None):
        self.updates.append((index, id, doc))


@pytest.mark.anyio
async def test_failed_forward_is_marked_on_the_record(monkeypatch):
    es = _ES()
    monkeypatch.setattr(audit, "get_es", lambda: es)
    monkeypatch.setattr(audit, "_enabled", lambda: True)
    monkeypatch.setattr(audit, "_data_stream_mode", lambda: False)
    monkeypatch.setattr(audit, "_get_sinks", lambda: [_FailingSink(), _OkSink()])

    await audit.write_event("execute")

    assert len(es.updates) == 1
    _, doc_id, doc = es.updates[0]
    assert doc_id == "abc123"
    assert doc == {"forward_failed": ["webhook"]}, "只该记下真的没送到的那个"


@pytest.mark.anyio
async def test_no_mark_when_every_sink_delivered(monkeypatch):
    es = _ES()
    monkeypatch.setattr(audit, "get_es", lambda: es)
    monkeypatch.setattr(audit, "_enabled", lambda: True)
    monkeypatch.setattr(audit, "_data_stream_mode", lambda: False)
    monkeypatch.setattr(audit, "_get_sinks", lambda: [_OkSink()])

    await audit.write_event("execute")
    assert es.updates == [], "正常情况下审计写入量不该增加"


@pytest.mark.anyio
async def test_data_stream_mode_does_not_update(monkeypatch):
    """data stream 只追加，update 会被 ES 拒绝 —— 不为了留痕破坏 ILM 的前提。"""
    es = _ES()
    monkeypatch.setattr(audit, "get_es", lambda: es)
    monkeypatch.setattr(audit, "_enabled", lambda: True)
    monkeypatch.setattr(audit, "_data_stream_mode", lambda: True)
    monkeypatch.setattr(audit, "_get_sinks", lambda: [_FailingSink()])

    await audit.write_event("execute")
    assert es.updates == []


@pytest.mark.anyio
async def test_a_sink_that_raises_counts_as_failed(monkeypatch):
    """契约说实现不该抛，但抛了也不能被当成送达。"""

    class _Boom(audit_sinks.Sink):
        kind = "webhook"

        async def write(self, event):
            raise RuntimeError("boom")

    es = _ES()
    monkeypatch.setattr(audit, "get_es", lambda: es)
    monkeypatch.setattr(audit, "_enabled", lambda: True)
    monkeypatch.setattr(audit, "_data_stream_mode", lambda: False)
    monkeypatch.setattr(audit, "_get_sinks", lambda: [_Boom()])

    await audit.write_event("execute")
    assert es.updates and es.updates[0][2] == {"forward_failed": ["webhook"]}
