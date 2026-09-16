"""产品自有索引的硬拒绝（index_whitelist.blocked_owned）。

背景：`IndexWhitelist.is_allowed` 在 patterns 为空时**恒返回 True**，而
`RST_INDEX_WHITELIST` 在 docker-compose.prod.yml 里的默认值就是空。也就是说在
默认部署上 `_check_index` 形同虚设 —— 任何登录账号都能把 `/api/execute` 指向
产品自己的存储：别人的查询历史和偏好、审计索引、通知配置文档（里面存着明文的
webhook_url）。同一条路也是 prompt injection 在 agentic 循环里的唯一落点。

所以自有索引这道闸必须和白名单无关。这里钉住三件事：
  1. 自有索引被挡住，精确名和通配都挡；
  2. 客户自己的数据源**不受影响** —— 尤其 `.alerts-security.*`，它是点号开头
     但属于客户，正是这个产品要读的东西。按点号前缀一刀切会直接打断告警功能；
  3. ES 的逗号多索引语法不能用来夹带。
"""
import sys
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent  # .../poc
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

import pytest  # noqa: E402

from backend import index_whitelist  # noqa: E402


@pytest.fixture
def owned(monkeypatch):
    """固定一组自有索引，别让测试跟着真实解析器的取值漂移。"""
    names = {".rst_copilot_userstate", ".rst_copilot_audit", "baseline-rules"}
    monkeypatch.setattr(index_whitelist.owned_indices, "owned_index_names", lambda: names)
    return names


@pytest.mark.parametrize(
    "index",
    [
        ".rst_copilot_userstate",
        "baseline-rules",
        ".rst_copilot_*",          # 通配同样要挡
        "*",                       # 「查全部」会扫到自有存储
        "baseline-*",
    ],
)
def test_owned_indices_are_blocked(owned, index):
    assert index_whitelist.blocked_owned(index) is not None


@pytest.mark.parametrize(
    "index",
    [
        "logs-nginx.access-default",
        "logs-*",
        # 客户的 Kibana 告警：点号开头，但是数据源不是内部存储。
        ".alerts-security.alerts-default",
        ".alerts-security.alerts-*",
        "kibana_sample_data_logs",
    ],
)
def test_customer_data_is_not_blocked(owned, index):
    assert index_whitelist.blocked_owned(index) is None


def test_comma_list_cannot_smuggle_an_owned_index(owned):
    """ES 把 index 当成逗号分隔的多索引列表。合法索引后面挂一个自有索引，
    整条请求都要被拒，不能只看第一段。"""
    assert index_whitelist.blocked_owned("logs-*,.rst_copilot_userstate") is not None


def test_include_exclude_prefix_is_stripped(owned):
    """`+` / `-` 是 ES 的包含排除前缀，不能用来绕过名字比对。"""
    assert index_whitelist.blocked_owned("+baseline-rules") is not None


def test_guard_is_independent_of_the_whitelist(owned, monkeypatch):
    """白名单为空（也就是默认部署）时这道闸照样生效 —— 这是它存在的全部理由。"""
    monkeypatch.setattr(index_whitelist, "_singleton", index_whitelist.IndexWhitelist([]))
    assert index_whitelist.get().is_allowed(".rst_copilot_userstate") is True
    assert index_whitelist.blocked_owned(".rst_copilot_userstate") is not None


def test_no_owned_indices_resolved_means_no_block(monkeypatch):
    """解析器全挂掉时返回空集合，这时候不该把所有查询都拒掉 —— 那是把一个
    读不到配置的故障放大成整个产品不可用。"""
    monkeypatch.setattr(index_whitelist.owned_indices, "owned_index_names", lambda: set())
    assert index_whitelist.blocked_owned("anything") is None
