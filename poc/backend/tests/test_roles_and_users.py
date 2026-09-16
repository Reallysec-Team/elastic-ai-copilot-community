"""阶段 03 · 角色与用户：每条规则先写"越权应当失败"。

这一组和 UI 改造不是一回事。前端按角色隐藏入口是礼貌，不是权限 —— 判断
标准是"把入口藏起来"之外，后端自己也拒。所以下面每条规则都成对出现：
一条证明越权被拒，一条证明合法路径没被顺手拦掉。

完成判定那两条在这里：
  * 角色改成只读后，同一个 cookie 立刻被写操作拒绝 —— 不需要重新登录
  * 停用某个账号后，它手上的会话立刻失效
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import session_auth, session_store, user_db, user_state  # noqa: E402
from backend.auth import _READ_ONLY_POST_PATHS  # noqa: E402

_PASSWORD = "Roles@12345"


@pytest.fixture
def accounts(monkeypatch):
    """三个账号，一档一个。返回可就地改的表 —— 测"改角色立刻生效"要它。

    打的是 `user_db._table`，也就是缓存读出来的那张表。真表在 Postgres 里，
    需要真库的用例在 test_user_db_postgres.py。这里要证明的是角色怎么被用，
    不是它存在哪。
    """
    pw_hash = session_auth.hash_password(_PASSWORD)
    table = {
        name: {"username": name, "password_hash": pw_hash, "role": role, "disabled": False}
        for name, role in (("boss", "admin"), ("ana", "analyst"), ("ro", "viewer"))
    }
    monkeypatch.setattr(user_db, "_table", lambda: table)
    monkeypatch.setattr(user_db, "enabled", lambda: True)
    return table


@pytest.fixture
def client(monkeypatch, tmp_path, accounts):
    """完整 ASGI 栈，撤销 conftest 那两处放行 —— 这组测的就是闸门本身。"""
    from fastapi.testclient import TestClient

    from backend import auth as auth_mod
    from backend import main

    monkeypatch.setenv("RST_SESSION_STORE", str(tmp_path / "sessions.json"))
    monkeypatch.setenv("RST_ADMIN_PASSWORD_HASH", session_auth.hash_password(_PASSWORD))
    for var in ("RST_SSO_ENABLED", "RST_ADMIN_TOKEN", "RST_GATEWAY_SHARED_SECRET",
                "RST_RBAC_ADMIN_GROUPS", "RST_RBAC_ANALYST_GROUPS", "RST_RBAC_VIEWER_GROUPS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(auth_mod, "session_valid", session_auth.session_valid)
    monkeypatch.setattr(auth_mod, "session_identity", session_auth.session_identity)
    session_store._reset_for_tests()
    session_auth._reset_throttle_for_tests()
    yield TestClient(main.app)
    session_store._reset_for_tests()


def _login(client, user: str) -> None:
    r = client.post("/api/auth/login", json={"username": user, "password": _PASSWORD})
    assert r.status_code == 200, r.text


def _is_read_only_refusal(resp) -> bool:
    return resp.status_code == 403 and resp.json().get("code") == "read_only"


# ─────────────────────── 只读角色不能写 ───────────────────────


@pytest.mark.parametrize("method,path", [
    ("post", "/api/settings"),
    ("post", "/api/feedback"),
    ("put", "/api/notify/smtp"),
    ("delete", "/api/notify/targets/x"),
    ("post", "/api/users"),
    ("patch", "/api/users/ana"),
])
def test_viewer_is_refused_every_write(client, method, path):
    """按 HTTP 方法拦，所以这条对"任一写接口"成立，不是对我记得挂的那几个。"""
    _login(client, "ro")
    assert _is_read_only_refusal(client.request(method.upper(), path, json={}))


def test_viewer_can_still_read(client):
    """一条把所有人都挡住的防护等于把可用性当安全用。"""
    _login(client, "ro")
    assert client.get("/api/me").status_code == 200


def test_viewer_can_still_log_out(client):
    """登出是白名单里的写 —— 否则只读账号进得来出不去。"""
    _login(client, "ro")
    assert client.post("/api/auth/logout").status_code == 200


@pytest.mark.parametrize("path", sorted(_READ_ONLY_POST_PATHS))
def test_viewer_may_still_ask_questions(client, path):
    """只读 = 能查不能改。这几条是"问题在 body 里"的读操作，全挡等于什么都不能做。

    只断言不是 read_only 拒绝 —— 422/400 是路由在说请求体不对，那正说明闸门放行了。
    """
    _login(client, "ro")
    assert not _is_read_only_refusal(client.post(path, json={}))


def test_a_write_post_is_still_refused(client):
    """白名单只放读语义的那几条，别顺手把整个 POST 都开了。"""
    _login(client, "ro")
    assert _is_read_only_refusal(client.post("/api/baseline/run", json={}))


def test_viewer_may_write_its_own_ui_state(client):
    """自己的界面状态不是共享状态。

    查询历史、偏好、保存的查询、分诊标记都走 PUT/DELETE /api/state/...，
    按方法拦会把它们一并拦掉 —— 只读账号连自己的主题和语言都存不下来，
    而没有任何别人看得见的东西被改。
    """
    _login(client, "ro")
    assert not _is_read_only_refusal(client.put("/api/state/pref/ui", json={"value": {}}))
    assert not _is_read_only_refusal(client.delete("/api/state/saved_query/q1"))


@pytest.mark.parametrize("kind", sorted(user_state.SHARED_KINDS))
def test_viewer_may_not_write_team_state(client, kind):
    """共享状态（_team 桶）是团队事实，不是个人偏好。

    冷启动验收 2026-09-12：只读账号在告警流里把「未处置」改成「已处置」，
    PUT /api/state/alert_status/... 200，整条告警对所有人消失 —— 因为整个
    /api/state/ 前缀都豁免了只读闸。现在只豁免 PERSONAL_KINDS。
    """
    _login(client, "ro")
    assert _is_read_only_refusal(client.put(f"/api/state/{kind}/x", json={"value": {}}))
    assert _is_read_only_refusal(client.delete(f"/api/state/{kind}/x"))


def test_analyst_writes_are_not_read_only_refused(client):
    """400 是路由说这个 kind 不对，正是我们要的：闸门放行了。"""
    _login(client, "ana")
    r = client.put("/api/state/not_a_kind/x", json={"value": 1})
    assert not _is_read_only_refusal(r)
    assert r.status_code == 400


# ─────────────────────── 管理操作只归管理员 ───────────────────────


@pytest.mark.parametrize("method,path,body", [
    ("put", "/api/notify/schedule", {}),
    # 这两条要给一份能过 pydantic 的请求体：body 校验在依赖之前跑，空 body 会先
    # 撞 422，那样测到的就不是这道闸了。
    ("post", "/api/notify/targets", {"name": "t", "webhook_url": "https://open.feishu.cn/x"}),
    ("put", "/api/notify/smtp", {"host": "h", "from_addr": "a@b.c"}),
    ("delete", "/api/notify/targets/x", {}),
    ("post", "/api/notify/deliveries/x/retry", {}),
    ("post", "/api/notify/targets/x/test", {}),
    ("post", "/api/baseline/rules", {}),
    ("delete", "/api/baseline/rules/x", {}),
    ("post", "/api/license/reload", {}),
    ("post", "/api/license/deactivate", {}),
])
def test_analyst_cannot_reach_the_admin_only_writes(client, method, path, body):
    """只读闸按方法判，挡的是 viewer —— analyst 的写是放行的，管理面只能靠路由自己拦。

    这十条以前一条都没拦。最狠的是 `PUT /api/notify/smtp`：只传 host 不传 password
    时已存的 `password_enc` 会原样留着，于是改一个 host 就能让下一封报告邮件带着
    客户的 SMTP 凭据登录到别人的服务器上。基线规则那两条写的是会下发到端点执行的
    osquery SQL；license 那两条能把整个部署打回未激活。
    """
    _login(client, "ana")
    r = client.request(method.upper(), path, json=body)
    assert r.status_code == 403, f"{method} {path} 应当只归管理员"


@pytest.mark.parametrize("path", ["/api/notify/config", "/api/notify/deliveries"])
def test_notify_reads_stay_open(client, path):
    """写归管理员，读不动 —— analyst 要能看投递记录，否则值班时查不了为什么没收到。"""
    _login(client, "ana")
    assert client.get(path).status_code != 403


@pytest.mark.parametrize("user", ["ana", "ro"])
def test_non_admin_cannot_reach_admin_endpoints(client, user):
    _login(client, user)
    r = client.get("/api/users")
    assert r.status_code == 403
    # 已经登录的人被告知"请先登录"会把他送回登录页去找一个登录给不了的东西。
    assert "角色" in r.json()["detail"]


def test_admin_can(client):
    _login(client, "boss")
    r = client.get("/api/users")
    assert r.status_code == 200
    assert {u["username"] for u in r.json()["users"]} == {"boss", "ana", "ro"}
    assert "password_hash" not in r.json()["users"][0]


# ─────────────── 完成判定 · 改角色立刻生效，不必重新登录 ───────────────


def test_demotion_takes_effect_on_the_next_request(client, accounts):
    """同一个 cookie，前一秒能写，后一秒不能 —— 中间没有重新登录。

    这是整个阶段的判定条件。会话记录里存着签发时的角色，如果授权读的是
    那一份，降级就会一直睡到会话过期才醒。
    """
    _login(client, "ana")
    assert not _is_read_only_refusal(client.post("/api/feedback", json={}))

    accounts["ana"]["role"] = "viewer"

    assert _is_read_only_refusal(client.post("/api/feedback", json={}))


def test_promotion_takes_effect_on_the_next_request(client, accounts):
    """反方向也要成立，否则"立刻生效"只是恰好拒得多。"""
    _login(client, "ana")
    assert client.get("/api/users").status_code == 403
    accounts["ana"]["role"] = "admin"
    assert client.get("/api/users").status_code == 200


# ─────────────── 完成判定 · 停用/删除让会话立刻失效 ───────────────


def test_disabling_an_account_kills_its_live_session(client, accounts):
    _login(client, "ana")
    assert client.get("/api/me").json()["authenticated"] is True

    accounts["ana"]["disabled"] = True

    me = client.get("/api/me")
    assert me.json()["authenticated"] is False
    # /api/me 是登录闸的豁免路径，所以拿一个不豁免的来证明是真被挡住了。
    assert client.get("/api/settings").status_code == 401


def test_deleting_an_account_kills_its_live_session(client, accounts):
    _login(client, "ana")
    accounts.pop("ana")
    assert client.get("/api/settings").status_code == 401


def test_a_disabled_account_cannot_log_in(client, accounts):
    accounts["ana"]["disabled"] = True
    r = client.post("/api/auth/login", json={"username": "ana", "password": _PASSWORD})
    assert r.status_code == 401


# ─────────── 阶段 02 欠的那半条：改密码只踢自己，不踢别人 ───────────


def test_one_users_password_change_does_not_sign_out_anyone_else(client, accounts):
    """阶段 02 只验到一半，因为当时只有一个账号 —— 现在有两个人可以对照了。

    签名密钥是全局的、且不再从口令派生（H4），所以改口令必须只作废按旧口令
    指纹签发的那些会话。真踢掉了别人，就等于全公司陪一个人改密码。
    """
    boss = client
    _login(boss, "boss")

    from fastapi.testclient import TestClient

    from backend import main

    ana = TestClient(main.app)
    _login(ana, "ana")

    accounts["ana"]["password_hash"] = session_auth.hash_password("Brand@New123")

    assert ana.get("/api/settings").status_code == 401     # 改的人自己被踢
    assert boss.get("/api/settings").status_code != 401    # 别人不受影响
    assert boss.get("/api/users").status_code == 200


# ─────────────────────── 管理接口的自伤保护 ───────────────────────


def test_admin_cannot_disable_or_delete_themselves(client):
    _login(client, "boss")
    assert client.patch("/api/users/boss", json={"disabled": True}).status_code == 400
    assert client.delete("/api/users/boss").status_code == 400


def test_last_admin_guard_lives_in_user_db():
    """判定在 user_db，不在路由 —— 每个调用点都得挡得住，包括管理员自己。

    以前这条用例是打桩 `_query` 之后直接调 `update_user`。判定现在必须跟
    `SELECT ... FOR UPDATE` 在同一个事务里（不锁行的话两个并发降级都会通过，
    实测能把管理员降到 0 个），所以不连库的这一半只测判定本身，端到端那一半
    在 test_user_db_postgres.py 的两条并发用例里。
    """
    with pytest.raises(user_db._LastAdmin):
        user_db._check_last_admin("boss", {"boss"}, True)
    # 还有别的在任管理员 → 放行
    user_db._check_last_admin("boss", {"boss", "other"}, True)
    # 这次改动本来就不拿掉管理员（比如只改密码）→ 放行
    user_db._check_last_admin("boss", {"boss"}, False)


def test_last_admin_signal_becomes_the_right_error_code(accounts, monkeypatch):
    """两个调用方各自把内部信号翻成自己那条错误码。"""
    def refuse(*a, **k):
        raise user_db._LastAdmin

    monkeypatch.setattr(user_db, "_write_guarding_admins", refuse)
    monkeypatch.setattr(user_db, "_ensure_table", lambda: None)

    with pytest.raises(ValueError) as e1:
        user_db.update_user("boss", role="viewer")
    assert e1.value.code == "last_admin_locked"
    with pytest.raises(ValueError) as e2:
        user_db.delete_user("boss")
    assert e2.value.code == "last_admin_undeletable"


def test_password_shorter_than_eight_is_refused(client):
    _login(client, "boss")
    r = client.post("/api/users", json={"username": "x", "password": "short", "role": "viewer"})
    assert r.status_code == 400


def test_unknown_role_is_refused(client):
    _login(client, "boss")
    r = client.post(
        "/api/users",
        json={"username": "x", "password": "longenough1", "role": "superuser"},
    )
    assert r.status_code == 400


# ─────────────────────── SSO 组 → 角色映射 ───────────────────────


@pytest.fixture
def sso(monkeypatch):
    """SSO 身份只有在配了 shared secret 时才可信 —— 否则任何直连客户端都能伪造。"""
    monkeypatch.setenv("RST_SSO_ENABLED", "1")
    monkeypatch.setenv("RST_GATEWAY_SHARED_SECRET", "s3cret")
    monkeypatch.setenv("RST_RBAC_ADMIN_GROUPS", "sec-admins")
    monkeypatch.setenv("RST_RBAC_ANALYST_GROUPS", "soc-l1,soc-l2")
    monkeypatch.setenv("RST_RBAC_VIEWER_GROUPS", "auditors")
    # conftest 那条 autouse fixture 把每个请求都当成已登录的管理员；这一组
    # 问的是"没有会话时组映射说了算什么",得先把它撤掉。
    from backend import auth, session_auth as sa

    monkeypatch.setattr(auth, "session_identity", sa.session_identity)


class _SsoReq:
    def __init__(self, groups: str):
        self.headers = {"x-auth-request-user": "u@example.com",
                        "x-auth-request-groups": groups,
                        "x-rst-gateway-token": "s3cret"}
        self.cookies: dict[str, str] = {}


@pytest.mark.parametrize("groups,expected", [
    ("sec-admins", "admin"),
    ("soc-l2", "analyst"),
    ("auditors", "viewer"),
    ("sec-admins,auditors", "admin"),   # 取最高的那一档
    ("nobody-knows-this", None),        # 没映射 = 没意见，不是只读
    ("", None),
])
def test_sso_groups_map_to_roles(sso, groups, expected):
    from backend import auth

    assert auth.effective_role(_SsoReq(groups)) == expected


def test_sso_deployment_does_not_honour_the_ops_token(sso, monkeypatch):
    """SSO 部署已经选了基于身份的鉴权，静态共享令牌是它的反面。"""
    from backend import auth

    monkeypatch.setenv("RST_ADMIN_TOKEN", "opstoken")

    class _TokenReq:
        headers = {"x-rst-admin-token": "opstoken", "x-rst-gateway-token": "s3cret"}
        cookies: dict[str, str] = {}

    assert auth.effective_role(_TokenReq()) is None
    assert auth.is_admin(_TokenReq()) is False
