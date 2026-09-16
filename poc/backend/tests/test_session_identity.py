"""阶段 02 底座：身份成为一等公民。

这一层测的不是"能登录"，而是四件在单用户模型下不成立、多用户下必须成立的事：
签名密钥不再随密码走、会话可以被服务端收回、`current_user()` 在密码登录下
说得出是谁、以及存量 `_shared` 数据在这次切换里不会消失。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import session_auth, session_store, user_db, user_state  # noqa: E402

_NOW = 1_700_000_000.0


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv("RST_SESSION_STORE", str(tmp_path / "sessions.json"))
    for var in ("RST_ADMIN_PASSWORD_HASH", "RST_ADMIN_USERNAME", "RST_SSO_ENABLED",
                "RST_SHARED_BUCKET_FALLBACK", "RST_GATEWAY_SHARED_SECRET"):
        monkeypatch.delenv(var, raising=False)
    session_store._reset_for_tests()
    yield
    session_store._reset_for_tests()


@pytest.fixture(autouse=True)
def _accounts(monkeypatch):
    """给这些用例一张用户表。

    阶段 03 起会话必须属于一个真实账号：`token_identity` 会去查这个人现在
    是什么角色、还在不在，查不到就当会话无效。下面的用例签发 alice / bob 的
    会话，所以 alice / bob 得存在。口令跟着环境走，`_set_password` 才还有效。
    """
    def table():
        h = session_auth.password_hash()
        return {
            name: {"username": name, "password_hash": h, "role": role, "disabled": False}
            for name, role in (("admin", "admin"), ("alice", "analyst"), ("bob", "viewer"))
        }

    monkeypatch.setattr(user_db, "_table", table)
    # conftest 的 autouse fixture 把 auth.session_identity 打成"永远是管理员"，
    # 好让其余几百条用例不用自己造会话。这一组测的就是这个函数本身，撤销它。
    from backend import auth

    monkeypatch.setattr(auth, "session_identity", session_auth.session_identity)


def _set_password(monkeypatch, password: str) -> None:
    monkeypatch.setenv("RST_ADMIN_PASSWORD_HASH", session_auth.hash_password(password))


class _Req:
    def __init__(self, token: str | None = None):
        self.cookies = {session_auth.COOKIE_NAME: token} if token else {}
        self.headers: dict[str, str] = {}


# ─────────────────── H4 · 签名密钥不再派生自密码 ───────────────────


def test_signing_key_survives_a_password_change(monkeypatch):
    """多用户下，任何人改密码都不能改动全局签名材料。"""
    _set_password(monkeypatch, "first")
    before = session_store.signing_key()
    _set_password(monkeypatch, "second")
    assert session_store.signing_key() == before


def test_signing_key_persists_across_process_restarts(monkeypatch, tmp_path):
    """密钥生成一次、落盘、不再重生成 —— 否则每次重启都等于全员登出。"""
    first = session_store.signing_key()
    session_store._reset_for_tests()  # 模拟重启：内存缓存清空，文件还在
    assert session_store.signing_key() == first
    assert (tmp_path / "sessions.json").exists()


def test_a_password_change_still_kills_the_sessions_it_issued(monkeypatch):
    """密钥稳定了，但"改密码=踢掉自己的会话"这条行为要保住 —— 现在靠记录
    会话签发时的密码指纹，而不是靠密钥跟着变。"""
    _set_password(monkeypatch, "first")
    tok = session_auth.issue_token(now=_NOW)
    assert session_auth.token_valid(tok, now=_NOW + 60)
    _set_password(monkeypatch, "second")
    assert not session_auth.token_valid(tok, now=_NOW + 60)


# ─────────────────── H3 · 会话可吊销、令牌带身份 ───────────────────


def test_token_names_a_server_side_record(monkeypatch):
    _set_password(monkeypatch, "pw")
    tok = session_auth.issue_token("alice", ["analyst"], now=_NOW)
    ident = session_auth.token_identity(tok, now=_NOW + 60)
    assert ident is not None
    assert ident["username"] == "alice"
    assert ident["roles"] == ["analyst"]
    assert ident["source"] == "password"


def test_revoking_a_session_kills_it_immediately(monkeypatch):
    """"停用某个员工"在 TTL 到期前必须真的生效 —— v1 令牌做不到这件事。"""
    _set_password(monkeypatch, "pw")
    tok = session_auth.issue_token("alice", now=_NOW)
    sid = tok.split(".")[1]
    assert session_auth.token_valid(tok, now=_NOW + 60)
    session_store.revoke(sid)
    assert not session_auth.token_valid(tok, now=_NOW + 60)


def test_revoke_all_targets_one_account_only(monkeypatch):
    _set_password(monkeypatch, "pw")
    alice = session_auth.issue_token("alice", now=_NOW)
    bob = session_auth.issue_token("bob", now=_NOW)
    assert session_store.revoke_all("alice") == 1
    assert not session_auth.token_valid(alice, now=_NOW + 60)
    assert session_auth.token_valid(bob, now=_NOW + 60)


def test_logout_withdraws_the_session_not_just_the_cookie(monkeypatch):
    """登出后即使把 cookie 原样贴回来也进不去。"""
    _set_password(monkeypatch, "pw")
    tok = session_auth.issue_token()  # 真实时间：下面走的是不带 now 的请求路径
    req = _Req(tok)
    assert session_auth.session_valid(req)
    session_auth.revoke_session(req)
    assert not session_auth.session_valid(_Req(tok))


def test_a_signature_alone_is_not_enough(monkeypatch):
    """签名正确但记录已被收回 —— 必须拒。否则吊销就只是装饰。"""
    _set_password(monkeypatch, "pw")
    tok = session_auth.issue_token(now=_NOW)
    session_store.revoke(tok.split(".")[1])
    assert session_auth.token_identity(tok, now=_NOW + 60) is None


@pytest.mark.parametrize("junk", ["", "garbage", "v2.sid.123", "v1.123.abc",
                                  "v2.sid.notanint.abc"])
def test_junk_and_v1_tokens_are_rejected(monkeypatch, junk):
    """v1 令牌不再受理：它的密钥已经不存在，而且它谁也不指认。"""
    _set_password(monkeypatch, "pw")
    assert session_auth.token_identity(junk, now=_NOW) is None


def test_expired_session_is_pruned_and_refused(monkeypatch):
    _set_password(monkeypatch, "pw")
    monkeypatch.setenv("RST_SESSION_TTL_HOURS", "1")
    tok = session_auth.issue_token(now=_NOW)
    assert session_auth.token_valid(tok, now=_NOW + 3599)
    assert not session_auth.token_valid(tok, now=_NOW + 3601)


# ─────────────────── H1 · current_user() 在密码登录下说得出是谁 ───────────────────


def test_current_user_answers_under_password_login(monkeypatch):
    """这是整个阶段的收口点：它以前恒为 None，所以审计不写 user、
    个人数据全落 _shared。"""
    from backend import auth

    _set_password(monkeypatch, "pw")
    tok = session_auth.issue_token("alice", ["admin"])
    user = auth.current_user(_Req(tok))
    assert user is not None
    assert user["username"] == "alice"
    assert user["source"] == "password"
    # 会话句柄不外泄：这份 dict 会被 /api/me 序列化给浏览器、并作为 audit 的
    # user 字段落库，两处都不该出现它。
    assert "sid" not in user


def test_current_user_is_none_without_a_session(monkeypatch):
    from backend import auth

    _set_password(monkeypatch, "pw")
    assert auth.current_user(_Req()) is None


def test_personal_state_lands_in_a_named_bucket_now(monkeypatch):
    from backend import auth

    _set_password(monkeypatch, "pw")
    tok = session_auth.issue_token("alice")
    owner = user_state.owner_for("history", auth.current_user(_Req(tok)))
    assert owner == "alice"


def test_two_users_do_not_share_personal_state():
    a = user_state.owner_for("history", {"username": "alice"})
    b = user_state.owner_for("history", {"username": "bob"})
    assert a != b
    # 团队级的东西仍然是团队级的 —— 分诊结论不能变成私有的。
    assert (user_state.owner_for("triage_status", {"username": "alice"})
            == user_state.owner_for("triage_status", {"username": "bob"}))


# ─────────────────── 迁移 · _shared 归首个管理员 + 双读期 ───────────────────


def test_the_configured_account_inherits_the_shared_bucket(monkeypatch):
    """升级当天历史不能消失：那些文档就是这个账号建的，它是当时唯一的账号。"""
    monkeypatch.setenv("RST_ADMIN_USERNAME", "admin")
    assert user_state.read_owners("admin", "history") == ["admin", "_shared"]


def test_nobody_else_inherits_it(monkeypatch):
    monkeypatch.setenv("RST_ADMIN_USERNAME", "admin")
    assert user_state.read_owners("bob", "history") == ["bob"]


def test_shared_kinds_are_untouched_by_the_fallback(monkeypatch):
    monkeypatch.setenv("RST_ADMIN_USERNAME", "admin")
    assert user_state.read_owners("_team", "triage_status") == ["_team"]


def test_the_dual_read_period_can_be_ended(monkeypatch):
    monkeypatch.setenv("RST_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("RST_SHARED_BUCKET_FALLBACK", "0")
    assert user_state.read_owners("admin", "history") == ["admin"]


def test_writes_never_go_back_to_the_shared_bucket(monkeypatch):
    """回退只对读生效。写一律进具名桶，所以每个 key 在下次改动时自然迁移。"""
    monkeypatch.setenv("RST_ADMIN_USERNAME", "admin")
    assert user_state.owner_for("history", {"username": "admin"}) == "admin"
