"""The user table — accounts, roles, and whether an account still works.

Why a database and not the state volume: `session_store` writes a JSON file
because a session is disposable (lose it, everyone signs in again). An account
is not. It is the thing an operator manages, backs up, and audits, and it is
the one piece of state whose loss the deployment cannot shrug off.

Why a *separate* Postgres and not the customer's Elasticsearch: the product's
standing promise is that it only reads the customer's ES. `user_state` already
bends that for UI state; identity is not the place to bend it further. Running
this instance is the operator's responsibility, and the deployment docs say so.

Not configured, no problem
--------------------------
Without `RST_USER_DB_URL` this module still answers, from the single account in
the environment (`RST_ADMIN_USERNAME` / `RST_ADMIN_PASSWORD_HASH`, role admin).
That keeps every caller written against one shape: nobody upstream branches on
"is there a user database". It is also the fallback for a licence without the
`multi_user` feature.

ponytail: one short-lived connection per operation, no pool. Reads come out of
the process cache below; the only queries left are login and the admin CRUD
calls, which are rare enough that a pool would be furniture. Add one when a
profile says otherwise.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any
from .api_errors import ApiError

logger = logging.getLogger("rst.user_db")

ROLES = ("admin", "analyst", "viewer")
DEFAULT_ROLE = "viewer"

_TABLE = "rst_users"


def _schema() -> str:
    # Built at call time, not baked into a module constant, so that a test can
    # repoint `_TABLE` at a scratch table. It could not before, and the tests
    # dropped the table a running dev gateway was using.
    return f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL,
    disabled      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


# Read-through cache of the whole table. Authorisation is checked on every
# request from synchronous code inside the middleware stack; a query per
# request would put a blocking round-trip on the event loop for a table with
# a few dozen rows in it.
#
# Every write in this module drops the cache, so "change a role / disable an
# account" takes effect on the next request without anyone signing in again —
# which is the behaviour phase 03 is judged on. The TTL is a backstop for the
# day a second worker exists and invalidation stops being process-local.
#
# ponytail: single uvicorn worker (Dockerfile has no `--workers`), same
# assumption session_store and the login throttle already run on.
_CACHE_TTL_S = 30.0
_cache: dict[str, dict[str, Any]] | None = None
_cache_at = 0.0
_first_admin: str | None = None
# 已经有一次后台刷新在跑。单 worker，所以一个普通布尔就够；
# 它只是防止 TTL 刚过的那一瞬几十个并发请求各自掉一个线程去查同一张表。
_refreshing = False


def url() -> str:
    return os.environ.get("RST_USER_DB_URL", "").strip()


def enabled() -> bool:
    return bool(url())


def owner_matches(entry_owner: Any, owner: str | None) -> bool:
    """一条按人归属的记录（会话、分析归档）能不能给 `owner` 看 / 删。

    - `owner is None`：调用方没有限定人（内部路径、单用户部署）→ 放行。
    - `entry_owner` 缺失：单用户 / demo 期写下的旧记录。**只在没配用户表时放行**
      —— 那时整个部署本来就只有一个人，"没写 owner" 和 "是我的" 是同一件事。
      配了用户表之后同样放行的话，那批旧记录对每个账号都可读、且可删，而这个
      兼容窗口是没有终点的。
    - 其余：要求精确相等。

    需要清理这批旧记录时走内部路径（`owner=None`），它仍然看得见。
    """
    if owner is None:
        return True
    if entry_owner is None:
        return not enabled()
    return entry_owner == owner


# ───────────────────────────── connection ─────────────────────────────


# Seconds to wait for the database. Short on purpose: a role lookup can end up
# on the request path (first call after the cache is dropped), so an
# unreachable database has to fail rather than hold the event loop for however
# long the OS decides a TCP connect should take — on Windows that is over a
# minute.
_CONNECT_TIMEOUT_S = 5


def _connect():
    import psycopg  # imported here so the dependency is optional when unused

    return psycopg.connect(url(), autocommit=True, connect_timeout=_CONNECT_TIMEOUT_S)


def _query(sql: str, params: tuple = (), *, fetch: bool = False) -> list[tuple]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if fetch else []


def init() -> None:
    """Create the table and seed the first administrator.

    This is the whole migration story. One table that has only ever had one
    shape does not need a migration tool; when a second shape arrives, this is
    where the `ALTER TABLE ... IF NOT EXISTS` goes.

    The seed account is the one already in the environment, so an existing
    single-operator deployment upgrades without anybody having to invent
    credentials — and it becomes the first administrator, which is what the
    `_shared` state bucket is handed to (see `user_state.read_owners`).
    """
    if not enabled():
        return
    from . import session_auth

    _ensure_table()
    rows = _query(f"SELECT count(*) FROM {_TABLE}", fetch=True)
    if rows and rows[0][0]:
        return
    _query(
        f"INSERT INTO {_TABLE} (username, password_hash, role) VALUES (%s, %s, 'admin')"
        " ON CONFLICT (username) DO NOTHING",
        (session_auth.username(), session_auth.password_hash()),
    )
    invalidate()
    logger.info("user_db_seeded", extra={"username": session_auth.username()})


# ───────────────────────────── reads ─────────────────────────────


def _fallback_table() -> dict[str, dict[str, Any]]:
    from . import session_auth

    name = session_auth.username()
    return {
        name: {
            "username": name,
            "password_hash": session_auth.password_hash(),
            "role": "admin",
            "disabled": False,
        }
    }


def _read_table_blocking() -> dict[str, dict[str, Any]] | None:
    """去数据库拿一次全表。失败返回 None，由调用方决定怎么兼容。"""
    global _cache, _cache_at
    try:
        rows = _query(
            f"SELECT username, password_hash, role, disabled FROM {_TABLE}", fetch=True
        )
    except Exception:  # noqa: BLE001
        # The database being unreachable must not turn into "everyone is an
        # admin". Serve the last known table if there is one, otherwise nobody.
        logger.warning("user_db_read_failed", exc_info=True)
        # 时间戳照样往前走：否则数据库一直不通时，每一个请求都会再试一次。
        # 代价是恢复最多晚一个 TTL，而那正是 TTL 本来的含义。
        _cache_at = time.time()
        # 冷启动就失败时把空表落进缓存。`None` 会让后面每个请求都走冷启动分支、
        # 各自再撞一次连接超时 —— 那正是这次要消掉的病。空表的含义是「谁都没有
        # 角色」，方向是 fail-closed；快速 403 好过整个事件循环停 5 秒之后再 403。
        if _cache is None:
            _cache = {}
        return None
    _cache = {
        r[0]: {
            "username": r[0],
            "password_hash": r[1],
            "role": r[2] if r[2] in ROLES else DEFAULT_ROLE,
            "disabled": bool(r[3]),
        }
        for r in rows
    }
    _cache_at = time.time()
    return _cache


async def _refresh_off_loop() -> None:
    global _refreshing
    try:
        await asyncio.to_thread(_read_table_blocking)
    finally:
        _refreshing = False


def _schedule_refresh() -> None:
    """把一次刷新挤出事件循环。不在循环里时就就地同步读。"""
    global _refreshing
    if _refreshing:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 没有运行中的事件循环（测试、CLI、启动期）—— 那就不存在「别卡住它」
        # 这个问题，直接同步读，行为和以前一样。
        _read_table_blocking()
        return
    _refreshing = True
    loop.create_task(_refresh_off_loop())


def _table() -> dict[str, dict[str, Any]]:
    """用户表。TTL 过期时**先返回旧表**，刷新放到线程里。

    这里之所以不能直接查库：`AuthMiddleware.dispatch` 是 async，它→
    `effective_role()` → `role_of()` → 这里。同步 `psycopg.connect` 卡的不是
    那一个请求，是**整个事件循环** —— 数据库慢或不可达时，网关上所有
    并发请求一起停最多 `_CONNECT_TIMEOUT_S` 秒，而 TTL 只有 30 秒，所以这事
    每分钟都会发生一次。

    旧表旧到什么程度是可接受的：每一次写都会 `invalidate()`，所以「改角色 /
    停用账号」仍然是下一个请求就生效；TTL 只是多 worker 那天的兜底。

    冷启动（`_cache is None`）没有旧表可返，那一次仍然要等 —— 但那是
    每进程一次，不是每 30 秒一次。
    """
    if not enabled():
        # Not cached: the environment is the source of truth and a test that
        # repoints RST_ADMIN_USERNAME must see it immediately.
        return _fallback_table()
    fresh = _cache is not None and time.time() - _cache_at < _CACHE_TTL_S
    if fresh:
        return _cache  # type: ignore[return-value]
    if _cache is not None:
        _schedule_refresh()
        return _cache
    # 冷启动：没有任何可以先用的东西，只能等这一次。
    return _read_table_blocking() or {}


def invalidate() -> None:
    """写完之后把表重新读一遍 —— 就地读，不是清空缓存等下一个请求去读。

    清空（`_cache = None`）会让紧接着的那一个请求走 `_table()` 的冷启动分支：在
    事件循环里同步 `psycopg.connect`，数据库慢或不可达时整个网关一起停最多
    `_CONNECT_TIMEOUT_S` 秒。而这个模块每一次写都调 `invalidate()`，于是那条
    「冷读每进程只有一次」的注释实际是「每改一次用户就来一次」。

    换成后台刷新也不行：那样下一个请求读到的是旧表，而「改角色 / 停用账号下一个
    请求就生效」正是这套角色要保证的东西。就地读两头都要得到 —— 每个写操作都在
    `asyncio.to_thread` 派出去的线程里跑（见 main.py 的用户管理路由），所以这次
    同步往返本来就不在事件循环上。

    读失败时 `_read_table_blocking` 会落一张空表（谁都没有角色，fail-closed），
    和它平时的错误处理是同一套。
    """
    global _cache, _cache_at, _first_admin
    _first_admin = None
    if not enabled():
        _cache = None
        _cache_at = 0.0
        return
    _read_table_blocking()


def get(username: str) -> dict[str, Any] | None:
    return _table().get((username or "").strip())


def list_users() -> list[dict[str, Any]]:
    """Every account, without the password hashes. Sorted so the UI is stable."""
    return sorted(
        ({k: v for k, v in rec.items() if k != "password_hash"} for rec in _table().values()),
        key=lambda r: str(r["username"]),
    )


def role_of(username: str) -> str | None:
    """Live role for `username`, or None when the account is gone or disabled.

    None is the answer authorisation wants for both cases: a deleted account and
    a disabled one are equally not allowed to do anything.
    """
    rec = get(username)
    if rec is None or rec.get("disabled"):
        return None
    return str(rec.get("role") or DEFAULT_ROLE)


def password_hash_of(username: str) -> str | None:
    rec = get(username)
    return str(rec["password_hash"]) if rec else None


def first_admin() -> str:
    """The account that inherits the pre-identity `_shared` state bucket.

    Under the fallback that is the configured account, which is also the one
    that wrote those documents. With a user table it is the seeded account —
    the same name, on any deployment that upgraded rather than started fresh.
    """
    global _first_admin
    from . import session_auth

    if not enabled():
        return session_auth.username()
    if _first_admin is not None:
        return _first_admin
    rows = _safe(
        lambda: _query(
            f"SELECT username FROM {_TABLE} WHERE role = 'admin'"
            " ORDER BY created_at, username LIMIT 1",
            fetch=True,
        ),
        [],
    )
    # Cached alongside the table because `read_owners` asks on every state
    # read; cleared by `invalidate()`, so promoting or deleting an admin is
    # picked up on the next write like everything else here.
    _first_admin = str(rows[0][0]) if rows else session_auth.username()
    return _first_admin


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        logger.warning("user_db_query_failed", exc_info=True)
        return default


def admin_count() -> int:
    return sum(
        1 for r in _table().values() if r.get("role") == "admin" and not r.get("disabled")
    )


# ───────────────────────────── writes ─────────────────────────────
#
# All of them raise ValueError with a message the API layer passes straight
# through to the operator: these are user-input errors, not faults.


def _ensure_table() -> None:
    """`CREATE TABLE IF NOT EXISTS`, on the write path as well as at startup.

    `init()` runs once per process, so a table that goes missing afterwards —
    a restored database, a DBA rebuilding the instance, a test suite pointed at
    the wrong URL — left the gateway serving its cache: reads looked fine and
    every write failed with a 500 until somebody restarted it. One cheap
    statement in front of writes (which are rare) makes that self-heal.
    """
    _query(_schema())


def _require_db() -> None:
    if not enabled():
        raise ApiError("user_db_not_configured")


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise ApiError("unknown_role", role=repr(role), choices=', '.join(ROLES))
    return role


class _LastAdmin(Exception):
    """内部信号：这次写会让部署失去最后一个管理员。调用方翻成自己的错误码。"""


def _check_last_admin(name: str, admins: set[str], may_remove_admin: bool) -> None:
    """判定本身。单独拎出来是为了能不连数据库就测（见 test_roles_and_users.py）；
    真并发下它成不成立，取决于调用方有没有先锁住这些行。"""
    if may_remove_admin and name in admins and len(admins) <= 1:
        raise _LastAdmin


def _write_guarding_admins(name: str, sql: str, params: tuple, *, may_remove_admin: bool) -> None:
    """在一个事务里跑一条写语句，先把在任管理员那几行锁住。

    「不许把最后一个管理员降级 / 停用 / 删掉」原来是「先 `admin_count()` 再写」，
    两步之间没有任何东西拦着第二个请求。实测两个线程同时降级两个不同的管理员：
    两边各自读到 2 个、各自放行，结束时管理员为 0 个，一个错都没报 —— 之后没人
    能进用户管理和设置，只能靠 RST_ADMIN_TOKEN 或直接改库救。路由是
    `asyncio.to_thread` 派出去的，所以这不是理论上的并发。

    `SELECT ... FOR UPDATE` 是关键：光靠 UPDATE 里嵌一个 count 子查询在
    READ COMMITTED 下仍然会双双通过（两条语句各自在对方提交前取快照）。锁住行之后
    第二个事务会等第一个提交，再重新读到最新的行版本，于是它看到的是 1 个。

    连接不开 autocommit —— 这个模块其余地方都开，因为它们是单语句。
    """
    import psycopg

    with psycopg.connect(url(), connect_timeout=_CONNECT_TIMEOUT_S) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT username FROM {_TABLE} WHERE role = 'admin' AND disabled = FALSE"
                " FOR UPDATE"
            )
            _check_last_admin(name, {r[0] for r in cur.fetchall()}, may_remove_admin)
            cur.execute(sql, params)
            if cur.rowcount == 0:
                raise ApiError("user_not_found", 404, name=name)
    invalidate()


def create_user(username: str, password_hash: str, role: str) -> None:
    _require_db()
    name = (username or "").strip()
    if not name:
        raise ApiError("username_required")
    _check_role(role)
    if get(name):
        raise ApiError("user_exists", name=name)
    _ensure_table()
    # 上面那次查重读的是进程缓存，写之前还有一个窗口 —— 两个并发的建号请求会双双
    # 通过，后到的那个撞主键，抛的是 psycopg 的 UniqueViolation：路由只翻
    # ApiError / ValueError，于是落成 500 加一段数据库报错，而这本该是一句
    # 「用户已存在」。让数据库来判重，按影响行数回答。
    inserted = _query(
        f"INSERT INTO {_TABLE} (username, password_hash, role) VALUES (%s, %s, %s)"
        " ON CONFLICT (username) DO NOTHING RETURNING username",
        (name, password_hash, role),
        fetch=True,
    )
    invalidate()
    if not inserted:
        raise ApiError("user_exists", name=name)


def update_user(username: str, *, password_hash: str | None = None,
                role: str | None = None, disabled: bool | None = None) -> None:
    """Change one account. Only the fields passed are touched.

    Demoting or disabling the last administrator is refused here rather than in
    the route, so it holds for every caller — there is no way to lock the
    deployment out of its own admin surface.
    """
    _require_db()
    name = (username or "").strip()
    rec = get(name)
    if not rec:
        raise ApiError("user_not_found", 404, name=name)
    if role is not None:
        _check_role(role)
    # 「这次改动会不会拿掉一个管理员」只看意图；「他现在还是不是在任管理员」由
    # `_write_guarding_admins` 在锁里现查 —— 拿缓存里的 rec 判，判的是三十秒前。
    may_remove_admin = (role is not None and role != "admin") or disabled is True
    sets, params = [], []
    if password_hash is not None:
        sets.append("password_hash = %s")
        params.append(password_hash)
    if role is not None:
        sets.append("role = %s")
        params.append(role)
    if disabled is not None:
        sets.append("disabled = %s")
        params.append(bool(disabled))
    if not sets:
        return
    sets.append("updated_at = now()")
    params.append(name)
    _ensure_table()
    try:
        _write_guarding_admins(
            name,
            f"UPDATE {_TABLE} SET {', '.join(sets)} WHERE username = %s",
            tuple(params),
            may_remove_admin=may_remove_admin,
        )
    except _LastAdmin:
        raise ApiError("last_admin_locked") from None


def delete_user(username: str) -> None:
    _require_db()
    name = (username or "").strip()
    rec = get(name)
    if not rec:
        raise ApiError("user_not_found", 404, name=name)
    _ensure_table()
    try:
        _write_guarding_admins(
            name,
            f"DELETE FROM {_TABLE} WHERE username = %s",
            (name,),
            may_remove_admin=True,
        )
    except _LastAdmin:
        raise ApiError("last_admin_undeletable") from None


def _reset_for_tests() -> None:
    invalidate()
