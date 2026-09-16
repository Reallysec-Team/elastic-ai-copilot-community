"""激活之后的心跳必须真的跑得通。

这条钉住一个在生产里存在了两个月的静默故障：`perform_heartbeat` 里用扁平的
`import content_store` 加载产品自己的模块，而那个模块用相对导入，于是每次心跳
都在 ImportError 上炸——吊销收不到、keyring 更新收不到、内容包收不到，日志里
只有一行 heartbeat_not_ok。没有任何测试走过"有许可时的一次心跳"。

打桩的是 lifecycle（网络那层），不是导入——导入必须真的发生。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import license_state as ls  # noqa: E402


class _FakeLife:
    def __init__(self):
        self.calls = 0

    def heartbeat_if_due(self, **kw):
        self.calls += 1
        # the two hooks perform_heartbeat wires in must be real callables
        assert callable(kw["content_sha_provider"]) and callable(kw["on_content_pack"])

    def is_revoked(self, _lic):
        return False

    def get_token(self):
        return None


def test_heartbeat_with_an_active_license_completes(monkeypatch):
    life = _FakeLife()
    monkeypatch.setattr(ls, "_license_id", "LIC-TEST-HB")
    monkeypatch.setattr(ls, "is_offline", lambda: False)
    monkeypatch.setattr(ls, "_get_life", lambda: life)
    monkeypatch.setattr(ls, "_refresh_session_if_due", lambda _l: None)

    async def _metrics():
        return {}
    monkeypatch.setattr(ls, "_heartbeat_metrics", _metrics)

    ok = asyncio.run(ls.perform_heartbeat())

    assert ok is True
    assert life.calls == 1, "lifecycle never reached — heartbeat died before the network step"
    assert ls._state.get("last_heartbeat_error") is None
