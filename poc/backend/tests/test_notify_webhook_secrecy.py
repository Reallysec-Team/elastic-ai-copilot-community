"""投递目标的 webhook URL 和签名密钥同档：加密存、不出接口。

飞书 / 钉钉的鉴权是签名密钥，那一份早就进了 secret_box。企业微信 / Slack /
Teams 没有签名 —— 它们的鉴权**就是 webhook URL 里那个 key**。所以 URL 本身就是
凭据，而它原来明文存在 ES 的配置文档里，也明文经 HTTP 回给界面。

这组测试钉的是三件事：写路径只落密文、读路径（给 HTTP 的那一份）不带明文、
存量明文能被启动时那趟迁移换掉。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend.notify import config as notify_config  # noqa: E402
from backend.notify import secret_box  # noqa: E402

_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=super-secret-key"


class _FakeDoc:
    """最小的配置文档替身：`_read_doc` / `_write_doc` 就够这几条路径用。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.writes = 0

    async def read(self, *, strict: bool = True):
        # 真的 `_read_doc` 现在按 strict 分流（写路径读不到就抛，纯读退默认值），
        # 替身跟着收这个参数即可 —— 它永远读得到。
        return self.cfg, 1, 1

    async def write(self, cfg, seq, term):
        self.cfg = cfg
        self.writes += 1


@pytest.fixture
def doc(monkeypatch, tmp_path):
    # 每个用例一把新钥匙，免得测试之间靠一个文件互相影响。
    monkeypatch.setenv("RST_SECRET_KEY_FILE", str(tmp_path / "key"))
    secret_box.reset_cache()
    d = _FakeDoc({"targets": [], "schedule": {}, "smtp": {}})
    monkeypatch.setattr(notify_config, "_read_doc", d.read)
    monkeypatch.setattr(notify_config, "_write_doc", d.write)
    return d


async def _new_target(name="值班群"):
    return await notify_config.upsert_target({
        "channel": "wecom",
        "name": name,
        "webhook_url": _URL,
        "periods": ["daily"],
    })


@pytest.mark.asyncio
async def test_saved_target_holds_no_plaintext_url(doc):
    await _new_target()
    stored = doc.cfg["targets"][0]
    assert "webhook_url" not in stored, "明文不该落进配置文档"
    assert stored["webhook_url_enc"]
    assert secret_box.decrypt(stored["webhook_url_enc"]) == _URL


@pytest.mark.asyncio
async def test_redacted_read_exposes_host_only(doc):
    cfg = await _new_target()
    t = cfg["targets"][0]
    assert "webhook_url" not in t
    assert "webhook_url_enc" not in t
    assert t["webhook_set"] is True
    # 主机名要留着 —— 界面上得看出这条发去哪个平台。
    assert t["webhook_host"] == "qyapi.weixin.qq.com"
    # 主机名里不能带上 key。
    assert "super-secret-key" not in str(t)


@pytest.mark.asyncio
async def test_raw_read_gives_the_sender_the_url(doc):
    await _new_target()
    tid = doc.cfg["targets"][0]["id"]
    raw = await notify_config.get_target_raw(tid)
    assert raw["webhook_url"] == _URL


@pytest.mark.asyncio
async def test_editing_without_the_url_keeps_it(doc):
    """界面读不到明文，所以「只改个名字」的编辑必须允许不重填 URL。"""
    await _new_target()
    tid = doc.cfg["targets"][0]["id"]
    await notify_config.upsert_target({
        "id": tid,
        "channel": "wecom",
        "name": "改了个名",
        "periods": ["daily"],
    })
    raw = await notify_config.get_target_raw(tid)
    assert raw["name"] == "改了个名"
    assert raw["webhook_url"] == _URL


@pytest.mark.asyncio
async def test_new_target_still_requires_a_url(doc):
    with pytest.raises(ValueError):
        await notify_config.upsert_target({
            "channel": "wecom", "name": "没填 URL", "periods": [],
        })


@pytest.mark.asyncio
async def test_legacy_plaintext_is_still_readable(doc):
    """升级不该让存量目标突然发不出去。"""
    doc.cfg["targets"] = [{
        "id": "legacy", "channel": "wecom", "name": "老目标",
        "webhook_url": _URL, "periods": [], "enabled": True,
        "alert_severity_threshold": "high",
    }]
    raw = await notify_config.get_target_raw("legacy")
    assert raw["webhook_url"] == _URL

    cfg = await notify_config.get_config()
    assert "webhook_url" not in cfg["targets"][0]
    assert cfg["targets"][0]["webhook_host"] == "qyapi.weixin.qq.com"


@pytest.mark.asyncio
async def test_migration_encrypts_and_is_idempotent(doc):
    doc.cfg["targets"] = [{
        "id": "legacy", "channel": "wecom", "name": "老目标",
        "webhook_url": _URL, "periods": [], "enabled": True,
    }]
    assert await notify_config.migrate_plaintext_webhook_urls() == 1
    stored = doc.cfg["targets"][0]
    assert "webhook_url" not in stored
    assert secret_box.decrypt(stored["webhook_url_enc"]) == _URL

    # 第二趟没得改，也不该再写一次。
    before = doc.writes
    assert await notify_config.migrate_plaintext_webhook_urls() == 0
    assert doc.writes == before

def test_delivery_errors_do_not_carry_the_webhook_path():
    """投递失败的 error 不只进日志 —— 它写进 outbox 文档，再由
    /api/notify/deliveries 回到界面上。而对飞书 / Slack / 企业微信来说，
    webhook 的路径本身就是凭据，正是这个文件其它用例在保的东西。"""
    from backend.notify.outbox import _scrub

    out = _scrub("POST https://open.feishu.cn/open-apis/bot/v2/hook/abc-secret failed: 404")
    assert "abc-secret" not in out
    assert "open.feishu.cn" in out, "主机要留着，否则排障时不知道是发给谁失败的"

    out = _scrub("timeout to https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SECRET")
    assert "SECRET" not in out

    assert _scrub(RuntimeError("timeout")) == "timeout"
    assert len(_scrub("x" * 500)) == 200
