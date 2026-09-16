"""共享测试前提。

登录默认开启后，任何直接打 `/api/*` 的 TestClient 都会撞上 401。这些用例
测的是路由和业务逻辑，不是那道门 —— 让它们每条都先去登录一次，只会把
"这条路由算错了" 的失败信息淹没在 401 里。

所以这里统一把它们当成"已登录的运维在操作"。门本身由
test_session_auth.py 覆盖：令牌签发/过期/改签名/换密码/限流，外加一条
真正走 TestClient、不吃这个 fixture 的路由级拦截测试。
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

# The unactivated-trial counter persists to disk on purpose (a uvicorn restart
# must not hand out a fresh day's quota). Under pytest that made the suite
# stateful across RUNS: the counter landed in poc/quota.json, and once five
# accumulated calls hit RST_TRIAL_DAILY_LIMIT every license-gated route started
# answering 402 — test_platform_ops_route's refund test failed on the sixth
# `pytest` invocation and passed again after deleting the file. Point the
# counter at a throwaway path before license_state is imported, so each run
# starts from zero.
os.environ.setdefault("RST_QUOTA_FILE", str(Path(tempfile.gettempdir()) / "rst-test-quota.json"))
# 同一个原因的另一半：未激活试用额度默认只有 5 次，而一次全量跑会打很多条受闸
# 路由（`@llm_post` 标了的都算），第六次开始全线 402 —— 失败在哪取决于收集顺序。
# 额度闸本身由 test_license_gate.py 覆盖（它自己打桩 consume_unactivated_quota）。
os.environ.setdefault("RST_TRIAL_DAILY_LIMIT", "1000000")
# 四个付费能力的引擎是 SEC-CC-1 密封件（premium_src/ 里的明文，git + docker 双
# ignore）。测试要跑这些能力就得走开发逃生舱：这个变量 + 那个目录同时存在。
# 没有 premium_src 的 checkout（CI、开源仓）里，碰这些能力的用例会 FeatureLocked
# —— 用 `premium_core` fixture 让它们 skip 而不是红。
os.environ.setdefault("RSTLIC_DEV_UNSEALED", "1")
try:
    Path(os.environ["RST_QUOTA_FILE"]).unlink()
except OSError:
    pass

# Same reasoning for the session store: it holds the signing key and every live
# session, and its default path is inside the checkout. Without this the suite
# would write poc/sessions.json and carry sessions between runs.
os.environ.setdefault(
    "RST_SESSION_STORE", str(Path(tempfile.gettempdir()) / "rst-test-sessions.json")
)
try:
    Path(os.environ["RST_SESSION_STORE"]).unlink()
except OSError:
    pass

# 同理，许可证记录也别读这台机器上真装着的那张。它是模块级状态：任何一条用
# `with TestClient(app)` 的用例都会跑 lifespan，lifespan 会 reload_license，于是
# 开发机上那张很久没心跳的许可被读进进程，之后每条打受闸路由的用例都吃 403
# heartbeat_lost —— 结果取决于收集顺序，也取决于跑的人机器上装没装许可。
# 指到一个空路径上，全量跑和全新 checkout / CI 看到的是同一件事：未激活。
os.environ.setdefault(
    "RST_LICENSE_FILE", str(Path(tempfile.gettempdir()) / "rst-test-license.json")
)
try:
    Path(os.environ["RST_LICENSE_FILE"]).unlink()
except OSError:
    pass

from backend import auth, session_auth  # noqa: E402

_PREMIUM_SRC = Path(__file__).resolve().parent.parent / "premium_src"


def premium_core(feature: str) -> dict:
    """The sealed core's plaintext namespace, or skip when the vault isn't here.

    Call it at the top of any test that exercises a paid engine (triage,
    investigation, detection rule, platform interpret). On a checkout without
    ``premium_src/`` — CI, the open-source repo — those tests skip with a
    reason instead of failing on FeatureLocked, and the rest of the suite
    keeps meaning something.
    """
    from backend import feature_unlock
    from rstlic_features import FeatureLocked
    try:
        return feature_unlock.load_premium(feature)
    except FeatureLocked as e:
        pytest.skip(f"premium_src/ not present for {feature} (build-vault input): {e}")


@pytest.fixture(autouse=True)
def authenticated_operator(monkeypatch):
    """把每个请求当作携带有效会话 —— 见模块 docstring。

    阶段 03 起要打两处。`session_valid` 只喂中间件的登录闸；授权走
    `current_user()` → `effective_role()`，它读的是 `session_identity`。只打前者
    的话请求能进门，却谁也不是，于是每个 require_admin 都 403。

    身份就是配置里那个账号 —— 没有用户库时 `user_db` 也正是这么回答的，所以
    这里给出的名字能一路解析成 admin 角色。要测真实闸门的用例照旧自己撤销
    （见 test_session_auth.py::real_gate）。
    """
    monkeypatch.setattr(auth, "session_valid", lambda request: True)
    monkeypatch.setattr(
        auth, "session_identity",
        lambda request: {"username": session_auth.username(), "roles": ["admin"],
                         "source": "password"},
    )


@pytest.fixture(autouse=True)
def rst_logs_reach_caplog(monkeypatch):
    """让 `rst.*` 的日志能被 caplog 抓到。

    `configure_logging()` 给 `rst` 树设了 `propagate: False`（生产上对的：日志
    只走那一个 JSON handler，不重复打到 root）。但 caplog 的 handler 装在 root
    上，所以任何断言日志的测试，能不能通过取决于本进程此前有没有导入过
    backend.main —— 也就是取决于测试收集顺序。CI 与本地的跳过集合不同，
    test_a_long_outage_is_capped_and_says_so 就是这样在 CI 上红、本地绿的。
    """
    monkeypatch.setattr(logging.getLogger("rst"), "propagate", True)


@pytest.fixture(autouse=True)
def rate_limits_off(monkeypatch):
    """限流桶在测试进程里放到很大。

    桶是按 (IP, 路径) 计数的进程内状态，而所有 TestClient 都是同一个 IP、同一个
    app —— 一个文件里连打三十次 `/api/platform/interpret` 就会撞上 30 次/分的
    默认值，于是「这条路由算错了」变成了取决于收集顺序的 429。真正测限流的用例
    自己设 RST_RATELIMIT_*（见 test_session_auth.py）。
    """
    from backend import llm_cost, rate_limit

    for env_var, _ in llm_cost.rate_limits().values():
        if env_var:
            monkeypatch.setenv(env_var, "100000")
    rate_limit.reload()
    yield
    rate_limit.reload()
