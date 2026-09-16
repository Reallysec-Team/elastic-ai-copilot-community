"""ES 短暂读不到的时候，不许把已有的东西覆盖掉或者半永久地记错。

两条都是「`except Exception` 兜太宽」的同一种病，但后果不一样：
一条毁数据（投递配置被清空重写），一条毁映射（归档索引由动态映射建出来）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import analysis_store  # noqa: E402
from backend.notify import config as notify_config  # noqa: E402


class _Boom(Exception):
    """既不是 NotFoundError 也不是 index_not_found —— 就是读不到。"""


@pytest.mark.asyncio
async def test_a_read_failure_never_overwrites_the_notify_config(monkeypatch):
    """写路径上读不到 = 不知道现在有什么，这时候写等于清空。

    原来这里 `except Exception` 把超时也当成「文档不存在」，返回默认值 + seq_no
    为 None，于是保存动作写出去的是一次不带 CAS 的全量覆盖：已配的投递目标、
    SMTP 凭据、订阅周期一起没了，ES 侧也拦不住。
    """
    written: list[dict] = []

    class _ES:
        async def get(self, **kw):
            raise _Boom("connection timed out")

        async def index(self, **kw):
            written.append(kw)

    monkeypatch.setattr(notify_config, "get_es", lambda: _ES())

    with pytest.raises(_Boom):
        await notify_config.save_smtp({
            "host": "mail.example.com", "port": 587, "from_addr": "a@b.c",
        })
    assert written == [], "读失败之后不该写出任何东西"


@pytest.mark.asyncio
async def test_a_read_failure_still_lets_the_page_render(monkeypatch):
    """纯读退回默认值 —— 少显示几行，不毁数据。界面不该因为 ES 打嗝整页崩掉。"""

    class _ES:
        async def get(self, **kw):
            raise _Boom("connection timed out")

    monkeypatch.setattr(notify_config, "get_es", lambda: _ES())
    cfg = await notify_config.get_config(redact=True)
    assert cfg["targets"] == []


@pytest.mark.asyncio
async def test_a_failed_index_create_is_retried_not_remembered(monkeypatch):
    """网关比 ES 先起来是客户自带 ELK 的常态，不能因此把索引让给动态映射。

    原来无论成败都置 `_index_ready = True`：ES 恢复后第一次写由动态映射建索引，
    owner 变成 text，`{"term": {"owner": …}}` 从此匹配不上——分析记录页对这些
    用户永远是空的。
    """
    monkeypatch.setattr(analysis_store, "_index_ready", False)
    calls = {"exists": 0}

    class _Down:
        class indices:
            @staticmethod
            async def exists(**kw):
                calls["exists"] += 1
                raise _Boom("connection refused")

    await analysis_store._ensure_index(_Down())
    assert analysis_store._index_ready is False, "建索引失败不该被记成已就绪"

    class _Up:
        class indices:
            @staticmethod
            async def exists(**kw):
                calls["exists"] += 1
                return False

            @staticmethod
            async def create(**kw):
                return {"acknowledged": True}

    await analysis_store._ensure_index(_Up())
    assert analysis_store._index_ready is True
    assert calls["exists"] == 2, "第二次要真的重试，而不是被 ready 短路掉"


@pytest.mark.asyncio
async def test_losing_the_create_race_counts_as_ready(monkeypatch):
    """抢建输了等于成功，别把它也当失败去无限重试。"""
    monkeypatch.setattr(analysis_store, "_index_ready", False)

    class _Race:
        class indices:
            @staticmethod
            async def exists(**kw):
                return False

            @staticmethod
            async def create(**kw):
                raise _Boom("resource_already_exists_exception")

    await analysis_store._ensure_index(_Race())
    assert analysis_store._index_ready is True
