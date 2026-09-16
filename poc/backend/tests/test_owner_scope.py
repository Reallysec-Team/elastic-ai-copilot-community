"""归属判定：配了用户表之后，空 owner 的旧记录不再对所有人放行。

会话和分析归档都按人存。单用户 / demo 期写下的那批记录没有 owner 字段，而两个
存储原来都无条件放行它们（注释说是有意的向后兼容）。兼容窗口没有终点：部署一旦
切到多用户，那批记录对每个账号都可读、且可删。

现在的规矩是：没配用户表 → 照旧放行（那时整个部署本来就只有一个人）；配了 →
空 owner 不再匹配任何具体的人。清理它们走内部路径（`owner=None`），那条仍然
看得见。
"""
from __future__ import annotations

import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import analysis_store, conversation, user_db  # noqa: E402


def test_unscoped_caller_sees_everything(monkeypatch):
    """内部路径不限定人 —— 迁移和清理靠的就是它。"""
    monkeypatch.setenv("RST_USER_DB_URL", "postgresql://x/y")
    assert user_db.owner_matches(None, None) is True
    assert user_db.owner_matches("alice", None) is True


def test_single_user_deployment_still_allows_legacy(monkeypatch):
    """没配用户表：整个部署只有一个人，「没写 owner」和「是我的」是同一件事。"""
    monkeypatch.delenv("RST_USER_DB_URL", raising=False)
    assert user_db.owner_matches(None, "admin") is True


def test_multi_user_denies_legacy(monkeypatch):
    """配了用户表：空 owner 不再匹配任何具体的人。"""
    monkeypatch.setenv("RST_USER_DB_URL", "postgresql://x/y")
    assert user_db.owner_matches(None, "alice") is False


def test_exact_match_always_wins(monkeypatch):
    for url in ("", "postgresql://x/y"):
        if url:
            monkeypatch.setenv("RST_USER_DB_URL", url)
        else:
            monkeypatch.delenv("RST_USER_DB_URL", raising=False)
        assert user_db.owner_matches("alice", "alice") is True
        assert user_db.owner_matches("alice", "bob") is False


def test_both_stores_use_the_same_rule():
    """两个存储各写过一份一模一样的判定 —— 现在是同一个函数，别再分叉。"""
    assert conversation._owner_matches is user_db.owner_matches
    assert analysis_store._owner_matches is user_db.owner_matches
