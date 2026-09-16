"""Tests for user_state owner bucketing (pure — no ES needed).

The owner resolution is what makes per-analyst isolation (personal kinds) vs
team-wide sync (shared kinds) correct, so it's worth pinning.
"""
from __future__ import annotations

import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent  # .../poc
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import user_state  # noqa: E402


def test_shared_kinds_always_team():
    # triage disposition / saved runs are team-wide regardless of who writes.
    assert user_state.owner_for("triage_status", None) == "_team"
    assert user_state.owner_for("triage_status", {"username": "alice"}) == "_team"
    assert user_state.owner_for("triage_result", {"username": "bob"}) == "_team"


def test_personal_kinds_key_on_user():
    assert user_state.owner_for("pref", {"username": "alice"}) == "alice"
    assert user_state.owner_for("history", {"username": "carol"}) == "carol"
    assert user_state.owner_for("saved_query", {"username": "dave"}) == "dave"


def test_personal_kinds_fall_back_to_shared_without_sso():
    assert user_state.owner_for("pref", None) == "_shared"
    assert user_state.owner_for("history", None) == "_shared"
    assert user_state.owner_for("pref", {}) == "_shared"  # no username


def test_kind_whitelist():
    for k in ("pref", "history", "saved_query", "triage_status", "triage_result"):
        assert k in user_state.ALLOWED_KINDS
    assert "evil" not in user_state.ALLOWED_KINDS
    assert "../etc" not in user_state.ALLOWED_KINDS


def test_kinds_the_frontend_writes_are_all_allowed():
    """Every kind the SPA writes must be listed here or the write 400s at the
    gateway. The detection-rule library shipped broken because `detection_rule`
    was never added — the feature looked complete and silently saved nothing."""
    for k in ("detection_rule", "alert_status"):
        assert k in user_state.ALLOWED_KINDS


def test_team_facts_are_shared_not_per_user():
    """A disposition or a saved rule belongs to the shift, not to whoever
    clicked. Landing these in PERSONAL_KINDS would hide one analyst's false
    positive mark from the next."""
    for k in ("triage_status", "detection_rule", "alert_status"):
        assert user_state.owner_for(k, {"username": "alice"}) == "_team"
    # Personal state stays keyed to the user.
    assert user_state.owner_for("pref", {"username": "alice"}) == "alice"
