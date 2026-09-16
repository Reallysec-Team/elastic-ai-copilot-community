"""Deactivate clears the local activation record → back to unactivated/demo.

Isolated with MemoryStorage so the test never touches the real license.json.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import license_state as ls  # noqa: E402
from rstlic_storage import MemoryStorage  # noqa: E402


def test_deactivate_clears_token_and_reverts_to_unactivated(monkeypatch):
    # Arrange: a "live" storage carrying a token + session material + keyring.
    mem = MemoryStorage()
    mem.set(ls._keys.token, "dummy.token")
    mem.set(ls._keys.session_token, "sess-token")
    mem.set(ls._keys.session_secret, "sess-secret")
    mem.set(ls._keys.feature_keyring, '{"alert_triage": "wrapped"}')
    mem.set(ls._keys.state_lid, "LIC-TEST-DEACT")
    monkeypatch.setattr(ls, "_storage", mem)
    monkeypatch.setattr(ls, "_life", None)  # rebuild lifecycle against mem

    # Act
    state = asyncio.run(ls.deactivate())

    # Assert: state is unactivated, no features, storage wiped.
    assert state["status"] == ls.STATUS_UNACTIVATED
    assert state["features"] == []
    assert state["license_id"] is None
    for k in (ls._keys.token, ls._keys.session_token, ls._keys.session_secret,
              ls._keys.feature_keyring, ls._keys.state_lid):
        assert mem.get(k) in ("", None), f"{k} not cleared"


def test_deactivate_is_idempotent(monkeypatch):
    mem = MemoryStorage()
    monkeypatch.setattr(ls, "_storage", mem)
    monkeypatch.setattr(ls, "_life", None)

    first = asyncio.run(ls.deactivate())
    second = asyncio.run(ls.deactivate())

    assert first["status"] == ls.STATUS_UNACTIVATED
    assert second["status"] == ls.STATUS_UNACTIVATED
