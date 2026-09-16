"""user_db 打真 Postgres —— 存储层自己的那一半。

角色怎么被用，在 test_roles_and_users.py（那里的表是内存里的）。这里只问
一件事：写进去的东西读得回来，且约束是数据库和 user_db 一起挡住的。

要跑起来：

    docker compose up -d userdb
    RST_TEST_PG_URL=postgresql://rst:rst@localhost:15433/rst_users \
        python -m pytest backend/tests/test_user_db_postgres.py

没有这个环境变量就整组跳过 —— 但跳过就等于没测，别把 skipped 当绿。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import session_auth, user_db  # noqa: E402

_URL = os.environ.get("RST_TEST_PG_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not _URL, reason="需要 RST_TEST_PG_URL 指向一个可写的 Postgres（见模块 docstring）"
)


# 刻意不是 rst_users。第一版用了真表名，于是这组测试把本地正在跑的网关那张
# 表 DROP 掉了 —— 网关照旧从缓存作答，看起来一切正常，写操作全 500。
_SCRATCH_TABLE = "rst_users_pytest"


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("RST_USER_DB_URL", _URL)
    monkeypatch.setenv("RST_ADMIN_USERNAME", "seeded_admin")
    monkeypatch.delenv("RST_ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.setattr(user_db, "_TABLE", _SCRATCH_TABLE)
    user_db.invalidate()
    user_db._query(f"DROP TABLE IF EXISTS {_SCRATCH_TABLE}")
    user_db.invalidate()
    yield user_db
    user_db._query(f"DROP TABLE IF EXISTS {_SCRATCH_TABLE}")
    user_db.invalidate()


def _pw() -> str:
    return session_auth.hash_password("Whatever@123")


def test_init_creates_the_table_and_seeds_the_configured_account(db):
    """升级路径：现有单账号部署不需要自己想一套凭据出来。"""
    db.init()
    assert db.get("seeded_admin")["role"] == "admin"
    assert db.first_admin() == "seeded_admin"


def test_init_is_idempotent_and_does_not_reseed(db):
    db.init()
    db.update_user("seeded_admin", role="admin")
    db.create_user("later", _pw(), "analyst")
    db.init()  # 重启
    assert {u["username"] for u in db.list_users()} == {"seeded_admin", "later"}


def test_crud_round_trip(db):
    db.init()
    db.create_user("ana", _pw(), "analyst")
    assert db.role_of("ana") == "analyst"

    db.update_user("ana", role="viewer")
    assert db.role_of("ana") == "viewer"

    db.update_user("ana", disabled=True)
    assert db.role_of("ana") is None       # 停用的人没有角色，和被删掉一样
    assert db.get("ana") is not None       # 但账号还在，可以恢复

    db.delete_user("ana")
    assert db.get("ana") is None


def test_a_write_is_visible_to_the_next_read_without_waiting_for_the_ttl(db):
    """缓存失效必须挂在写上。挂在 TTL 上的话，"改角色立刻生效"就成了
    "最多 30 秒后生效"，而那正是这一阶段要否掉的。"""
    db.init()
    db.create_user("ana", _pw(), "analyst")
    assert db.role_of("ana") == "analyst"
    db.update_user("ana", role="viewer")
    assert db.role_of("ana") == "viewer"


def test_a_write_recreates_a_table_that_went_missing(db):
    """表在进程启动后消失（库被重建、还原、或某个测试指错了 URL）时要自愈。

    真踩过：`init()` 一个进程只跑一次，表没了以后网关继续拿缓存作答 —— 读
    看着一切正常，写全是 500，直到有人想起来重启。
    """
    db.init()
    db._query(f"DROP TABLE {db._TABLE}")
    db.invalidate()

    db.create_user("ana", _pw(), "analyst")
    assert db.role_of("ana") == "analyst"


def test_duplicate_username_is_refused(db):
    db.init()
    db.create_user("ana", _pw(), "analyst")
    with pytest.raises(ValueError, match="已存在"):
        db.create_user("ana", _pw(), "viewer")


def test_unknown_role_never_reaches_the_table(db):
    db.init()
    with pytest.raises(ValueError, match="未知角色"):
        db.create_user("ana", _pw(), "root")


def test_the_last_admin_is_protected_in_the_database_layer(db):
    """路由层也拦，但那是礼貌。这里拦住才对每个调用点成立。"""
    db.init()
    db.create_user("ana", _pw(), "analyst")
    with pytest.raises(ValueError, match="最后一个"):
        db.update_user("seeded_admin", disabled=True)
    with pytest.raises(ValueError, match="最后一个"):
        db.delete_user("seeded_admin")

    db.update_user("ana", role="admin")   # 有第二个管理员了
    db.delete_user("seeded_admin")        # 现在可以走
    assert db.get("seeded_admin") is None


def test_password_hashes_never_leave_through_list_users(db):
    db.init()
    db.create_user("ana", _pw(), "analyst")
    assert all("password_hash" not in u for u in db.list_users())


def test_a_cold_process_with_an_unreachable_database_grants_nobody_anything(db):
    """失败方向要对：连不上库时不能有人还是"管理员"。

    说的是冷进程 —— 手上一张表都没有的时候。已经读到过表的进程会继续拿旧表答
    （`_read_table_blocking` 的注释写的就是这件事：有旧表就用旧表，没有就谁都不是），
    那是刻意的可用性取舍，不是这条用例要测的东西。
    """
    db.init()
    db._cache = None          # 冷进程：还没读到过任何表
    db._cache_at = 0.0

    def dead(*_a, **_k):
        raise OSError("connection refused")

    # 不能靠给个坏 URL：坏 URL 要等一次真实的连接超时。原来这里用 monkeypatch，
    # 但 db fixture 的清理跑在 monkeypatch 的撤销之前，于是最后一下自己把自己卡住了。
    original = db._connect
    db._connect = dead
    try:
        assert db.role_of("seeded_admin") is None
        assert db.list_users() == []
    finally:
        db._connect = original
        db.invalidate()


def test_a_warm_cache_keeps_answering_while_the_database_is_down(db):
    """反过来的一半：已经读到过表就继续用它答，直到 TTL 到期后刷新失败。"""
    db.init()
    db.invalidate()           # 读一次真表进缓存
    assert db.role_of("seeded_admin") == "admin"

    def dead(*_a, **_k):
        raise OSError("connection refused")

    original = db._connect
    db._connect = dead
    try:
        assert db.role_of("seeded_admin") == "admin", "旧表还在有效期内，应当照答"
    finally:
        db._connect = original
        db.invalidate()


def _two_admins(db) -> None:
    db._ensure_table()
    db._query(f"DELETE FROM {_SCRATCH_TABLE}")
    for n in ("a1", "a2"):
        db._query(
            f"INSERT INTO {_SCRATCH_TABLE} (username, password_hash, role)"
            " VALUES (%s, %s, 'admin')",
            (n, _pw()),
        )
    db.invalidate()


def _run_together(fn, args_list) -> list:
    """同时发起几个写，收集各自抛出来的东西。路由本来就是 asyncio.to_thread
    派出去的，所以并发是真的。"""
    import threading

    out: list = []
    lock = threading.Lock()

    def run(a):
        try:
            fn(*a)
            res = None
        except Exception as e:  # noqa: BLE001
            res = e
        with lock:
            out.append(res)

    threads = [threading.Thread(target=run, args=(a,)) for a in args_list]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def test_concurrent_demotions_cannot_empty_the_admin_seat(db):
    """两个管理员被同时降级，必须有一个被拒。

    修之前：两边各自 `admin_count()` 都读到 2、都放行，结束时管理员 0 个、
    一个错都没报。之后没人进得去用户管理和设置。
    """
    _two_admins(db)
    assert db.admin_count() == 2

    errs = _run_together(
        lambda n: db.update_user(n, role="viewer"), [("a1",), ("a2",)]
    )
    db.invalidate()

    refused = [e for e in errs if e is not None]
    assert len(refused) == 1, f"应当恰好拒掉一个，实际 {errs}"
    assert getattr(refused[0], "code", "") == "last_admin_locked"
    assert db.admin_count() == 1


def test_concurrent_deletes_cannot_empty_the_admin_seat(db):
    _two_admins(db)
    errs = _run_together(lambda n: db.delete_user(n), [("a1",), ("a2",)])
    db.invalidate()

    refused = [e for e in errs if e is not None]
    assert len(refused) == 1, f"应当恰好拒掉一个，实际 {errs}"
    assert getattr(refused[0], "code", "") == "last_admin_undeletable"
    assert db.admin_count() == 1


def test_demoting_one_of_two_admins_still_works(db):
    """闸门只挡最后一个 —— 正常的降级不能被误伤。"""
    _two_admins(db)
    db.update_user("a1", role="analyst")
    db.invalidate()
    assert db.role_of("a1") == "analyst"
    assert db.admin_count() == 1


def test_concurrent_creates_of_the_same_name_give_a_clean_error(db):
    """同名并发建号：一个成，另一个是「用户已存在」，不是 500。

    修之前后到的那个撞主键、抛 psycopg 的 UniqueViolation，路由只翻
    ApiError / ValueError，于是变成 500 加一段数据库报错。
    """
    db._ensure_table()
    db._query(f"DELETE FROM {_SCRATCH_TABLE}")
    db.invalidate()

    errs = _run_together(
        lambda: db.create_user("dup", _pw(), "viewer"), [(), ()]
    )
    db.invalidate()

    refused = [e for e in errs if e is not None]
    assert len(refused) == 1, f"应当恰好拒掉一个，实际 {errs}"
    assert getattr(refused[0], "code", "") == "user_exists"
    rows = db._query(
        f"SELECT count(*) FROM {_SCRATCH_TABLE} WHERE username = 'dup'", fetch=True
    )
    assert rows[0][0] == 1


def test_a_write_leaves_a_warm_cache_for_the_next_request(db):
    """写完之后不能留下一次冷读。

    冷读是在事件循环里同步连数据库 —— 库慢或不可达时整个网关一起停最多
    `_CONNECT_TIMEOUT_S` 秒，而每一次改用户都会调 `invalidate()`。所以
    `invalidate()` 就地把表读回来（写操作本来就在 asyncio.to_thread 的线程里），
    下一个请求直接命中缓存，同时仍然读得到刚改完的角色。
    """
    db.init()
    db.create_user("someone", _pw(), "analyst")

    def dead(*_a, **_k):
        raise AssertionError("下一次读又去连库了 —— 缓存没被写操作填热")

    original = db._connect
    db._connect = dead
    try:
        assert db.role_of("someone") == "analyst"
        assert {u["username"] for u in db.list_users()} >= {"someone"}
    finally:
        db._connect = original

    # 改完角色，下一个请求就得看到新的（同样不许再去连库）。
    db.update_user("someone", role="viewer")
    db._connect = dead
    try:
        assert db.role_of("someone") == "viewer"
    finally:
        db._connect = original
