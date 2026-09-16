"""user_db 的缓存：过期时先返回旧表，刷新挪出事件循环。

为什么值得钉住：`AuthMiddleware.dispatch` 是 async，它 → `effective_role()` →
`role_of()` → `_table()`。这里如果直接同步 `psycopg.connect`，卡住的不是那一个
请求而是**整个事件循环** —— 数据库慢或不可达时，网关上所有并发请求一起停最多
`_CONNECT_TIMEOUT_S` 秒。而 TTL 只有 30 秒，所以这事每分钟都会发生一次。

这几条测试防的就是有人日后把 `_table()` 改回「过期就地查库」。
"""
import sys
import time
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent  # .../poc
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

import pytest  # noqa: E402

from backend import user_db  # noqa: E402


@pytest.fixture(autouse=True)
def _multi_user(monkeypatch):
    """让 user_db 认为配了数据库，并且每条用例从干净的缓存开始。"""
    monkeypatch.setenv("RST_USER_DB_URL", "postgresql://stub/stub")
    monkeypatch.setattr(user_db, "_cache", None)
    monkeypatch.setattr(user_db, "_cache_at", 0.0)
    monkeypatch.setattr(user_db, "_refreshing", False)


def _rows(role: str):
    return [("alice", "hash", role, False)]


def test_cold_start_reads_and_caches(monkeypatch):
    calls = []
    monkeypatch.setattr(user_db, "_query", lambda *a, **k: calls.append(1) or _rows("admin"))

    assert user_db._table()["alice"]["role"] == "admin"
    assert len(calls) == 1
    # 第二次在 TTL 内，不该再查一次
    assert user_db._table()["alice"]["role"] == "admin"
    assert len(calls) == 1


@pytest.mark.anyio
async def test_expired_cache_serves_stale_without_blocking(monkeypatch):
    """TTL 过期后，`_table()` 必须立刻返回旧表 —— 查询发生在别的线程里。"""
    monkeypatch.setattr(user_db, "_query", lambda *a, **k: _rows("admin"))
    user_db._table()  # 预热

    # 让缓存过期，并把查询换成一个会睡很久的替身：如果 `_table()` 还在就地查库，
    # 这条用例就会卡在那 5 秒上，而不是立刻拿到旧表。
    monkeypatch.setattr(user_db, "_cache_at", time.time() - user_db._CACHE_TTL_S - 1)

    def slow(*a, **k):
        time.sleep(5)
        return _rows("viewer")

    monkeypatch.setattr(user_db, "_query", slow)

    t0 = time.monotonic()
    stale = user_db._table()
    elapsed = time.monotonic() - t0

    assert elapsed < 0.5, f"_table() 阻塞了 {elapsed:.2f}s —— 刷新又落回事件循环了"
    assert stale["alice"]["role"] == "admin", "过期时应该先给旧表，而不是空表"


@pytest.mark.anyio
async def test_refresh_is_not_scheduled_twice(monkeypatch):
    """TTL 刚过的那一瞬会有一批并发请求同时进来，它们只该合起来刷一次。"""
    monkeypatch.setattr(user_db, "_query", lambda *a, **k: _rows("admin"))
    user_db._table()
    monkeypatch.setattr(user_db, "_cache_at", time.time() - user_db._CACHE_TTL_S - 1)

    scheduled = []
    monkeypatch.setattr(user_db, "_query", lambda *a, **k: scheduled.append(1) or _rows("admin"))

    for _ in range(20):
        user_db._table()
    # 还没让出控制权，后台任务一次都还没跑
    assert scheduled == []
    assert user_db._refreshing is True


def test_without_a_loop_it_still_refreshes_synchronously(monkeypatch):
    """测试、CLI、启动期没有事件循环 —— 那时不存在「别卡住它」的问题，
    行为应该和以前一样：就地读，读完立刻可见。"""
    monkeypatch.setattr(user_db, "_query", lambda *a, **k: _rows("admin"))
    user_db._table()
    monkeypatch.setattr(user_db, "_cache_at", time.time() - user_db._CACHE_TTL_S - 1)
    monkeypatch.setattr(user_db, "_query", lambda *a, **k: _rows("viewer"))

    assert user_db._table()["alice"]["role"] == "viewer"


def test_unreachable_db_serves_last_known_table(monkeypatch):
    """数据库读不到不能变成「谁都没有角色」，更不能变成「谁都是管理员」。"""
    monkeypatch.setattr(user_db, "_query", lambda *a, **k: _rows("admin"))
    user_db._table()
    monkeypatch.setattr(user_db, "_cache_at", time.time() - user_db._CACHE_TTL_S - 1)

    def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(user_db, "_query", boom)
    assert user_db._table()["alice"]["role"] == "admin"


def test_cold_start_with_unreachable_db_grants_nothing(monkeypatch):
    """冷启动时读不到表，没有旧表可用 —— 这时答案必须是「没有人有权限」。"""
    def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(user_db, "_query", boom)
    assert user_db._table() == {}


def test_failed_read_does_not_retry_on_every_request(monkeypatch):
    """数据库一直不通时，别让每个请求都再撞一次连接超时。"""
    attempts = []

    def boom(*a, **k):
        attempts.append(1)
        raise RuntimeError("connection refused")

    monkeypatch.setattr(user_db, "_query", boom)
    user_db._table()          # 冷启动，撞一次
    assert len(attempts) == 1
    user_db._table()          # 时间戳已经往前走，这次落在 TTL 内
    assert len(attempts) == 1
