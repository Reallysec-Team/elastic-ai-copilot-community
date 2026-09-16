"""ES 连接改成从设置界面配 —— 保证「配错了还能配回来」的那几条。

安装向导把 ES 地址交给浏览器去填，风险是它同时也是设置页自己的依赖：存进一个
连不上的地址，等于把管理员锁在唯一能改回来的入口外面。所以这里守三件事：
落盘前的形状校验、保存后连接单例真的换掉、以及旧路径上的配置不会因为换到
持久化卷而静默消失。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import settings as gw_settings  # noqa: E402


# ───────────────────────── es.url 形状校验 ─────────────────────────


@pytest.mark.parametrize("bad", ["localhost:9200", "es.corp.local", "ftp://es:9200", "http://"])
def test_malformed_es_url_rejected(bad):
    with pytest.raises(ValueError, match="es.url"):
        gw_settings._validate_es_url({"es.url": bad})


@pytest.mark.parametrize("ok", ["http://localhost:9200", "https://es.corp.local:9243"])
def test_wellformed_es_url_accepted(ok):
    gw_settings._validate_es_url({"es.url": ok})


def test_blank_es_url_accepted():
    """留空 = 回落到默认值，不是错误。"""
    gw_settings._validate_es_url({"es.url": "   "})
    gw_settings._validate_es_url({})


# ───────────────────────── 保存后连接单例要换掉 ─────────────────────────


def test_saving_es_url_drops_the_connection_singleton(tmp_path, monkeypatch):
    """否则管理员改完地址，网关还连着旧集群，界面上却显示已保存。"""
    from backend import es_client

    monkeypatch.setenv("RST_SETTINGS_FILE", str(tmp_path / "settings.yml"))
    sentinel = object()
    monkeypatch.setattr(es_client, "_es", sentinel)

    gw_settings.save({"es.url": "http://new-es:9200"})

    assert es_client._es is None
    import os

    assert os.environ["ES_URL"] == "http://new-es:9200"


def test_password_is_masked_in_snapshot(monkeypatch):
    monkeypatch.setenv("ES_PASSWORD", "hunter2hunter2")
    snap = gw_settings.snapshot(mask_sensitive=True)
    assert "hunter2" not in snap["es.password"]
    assert snap["es.password"].startswith("<set ·")


def test_masked_password_sentinel_does_not_overwrite(tmp_path, monkeypatch):
    """界面把打码占位符原样回传时，必须理解成「这项别动」。"""
    import os

    monkeypatch.setenv("RST_SETTINGS_FILE", str(tmp_path / "settings.yml"))
    monkeypatch.setenv("ES_PASSWORD", "hunter2hunter2")
    gw_settings.save({"es.password": gw_settings.snapshot()["es.password"]})
    assert os.environ["ES_PASSWORD"] == "hunter2hunter2"


# ───────────────────────── 换到持久化路径不能丢配置 ─────────────────────────


def test_legacy_settings_file_is_migrated(tmp_path, monkeypatch):
    """老部署的 settings.yml 在镜像里；换成 state 卷上的路径时要带过去。"""
    legacy = tmp_path / "legacy.yml"
    legacy.write_text("alerts:\n  ingest_interval: 30\n", encoding="utf-8")
    target = tmp_path / "state" / "settings.yml"
    monkeypatch.setattr(gw_settings, "DEFAULT_PATH", legacy)
    monkeypatch.setenv("RST_SETTINGS_FILE", str(target))

    gw_settings.apply_overlay()

    assert target.exists()
    # 拷贝而非移动 —— 回滚到旧镜像时它还得在
    assert legacy.exists()
    import os

    assert os.environ["RST_ALERT_INGEST_INTERVAL_SECONDS"] == "30"


def test_migration_never_overwrites_an_existing_file(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy.yml"
    legacy.write_text("alerts:\n  ingest_interval: 30\n", encoding="utf-8")
    target = tmp_path / "state" / "settings.yml"
    target.parent.mkdir()
    target.write_text("alerts:\n  ingest_interval: 99\n", encoding="utf-8")
    monkeypatch.setattr(gw_settings, "DEFAULT_PATH", legacy)
    monkeypatch.setenv("RST_SETTINGS_FILE", str(target))

    gw_settings.apply_overlay()

    import os

    assert os.environ["RST_ALERT_INGEST_INTERVAL_SECONDS"] == "99"
