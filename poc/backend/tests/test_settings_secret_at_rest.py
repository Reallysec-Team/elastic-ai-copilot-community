"""settings.yml 里五个敏感值的落盘加密。

这条路径最承重：写坏了管理员连 ES 都配不回来。所以四件事都要钉住 ——
存量明文照读、保存后磁盘上不是明文、迁移幂等、密钥解不开时不把密文当口令用。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import settings as gw_settings  # noqa: E402
from backend.notify import secret_box  # noqa: E402


@pytest.fixture()
def yml(tmp_path, monkeypatch):
    """settings.yml + 密钥都指到临时目录，且不去碰真实模块单例。"""
    monkeypatch.setenv("RST_SETTINGS_FILE", str(tmp_path / "settings.yml"))
    monkeypatch.delenv("RST_SECRET_KEY", raising=False)
    monkeypatch.setenv("RST_SECRET_KEY_FILE", str(tmp_path / ".rst_secret_key"))
    secret_box.reset_cache()
    monkeypatch.setattr(gw_settings, "_reset_dependents", lambda: None)
    for var in gw_settings.ENV_MAPPING.values():
        monkeypatch.delenv(var, raising=False)
    yield tmp_path / "settings.yml"
    secret_box.reset_cache()


def _on_disk(p: Path) -> dict:
    return gw_settings._flatten(yaml.safe_load(p.read_text(encoding="utf-8")) or {})


def test_saved_secret_is_not_plaintext_on_disk(yml):
    gw_settings.save({"es.password": "hunter2", "es.url": "http://es:9200"})

    stored = _on_disk(yml)
    assert stored["es.password"].startswith(gw_settings._ENC_PREFIX)
    assert "hunter2" not in yml.read_text(encoding="utf-8")
    # 非敏感键照旧明文，管理员还能手改
    assert stored["es.url"] == "http://es:9200"


def test_encrypted_value_round_trips_into_env(yml):
    gw_settings.save({"alerts.webhook_secret": "s3cr3t"})
    for var in gw_settings.ENV_MAPPING.values():
        import os
        os.environ.pop(var, None)

    gw_settings.apply_overlay()

    import os
    assert os.environ["RST_ALERT_WEBHOOK_SECRET"] == "s3cr3t"


def test_legacy_plaintext_still_readable_then_migrated(yml):
    yml.write_text(
        yaml.safe_dump({"es": {"password": "old-plain", "url": "http://es:9200"}}),
        encoding="utf-8",
    )

    gw_settings.apply_overlay()

    import os
    assert os.environ["ES_PASSWORD"] == "old-plain"          # 存量照读
    assert _on_disk(yml)["es.password"].startswith(gw_settings._ENC_PREFIX)  # 顺手改写


def test_migration_is_idempotent(yml):
    yml.write_text(yaml.safe_dump({"es": {"password": "old-plain"}}), encoding="utf-8")

    assert gw_settings._encrypt_plaintext_secrets() == 1
    first = yml.read_text(encoding="utf-8")
    assert gw_settings._encrypt_plaintext_secrets() == 0     # 已密文 → 不再写
    assert yml.read_text(encoding="utf-8") == first


def test_unreadable_ciphertext_is_treated_as_unset(yml, monkeypatch):
    """密钥换了/丢了：值当作没设置，绝不能把密文当口令发给 ES。"""
    gw_settings.save({"es.password": "hunter2"})
    from cryptography.fernet import Fernet

    monkeypatch.setenv("RST_SECRET_KEY", Fernet.generate_key().decode())
    secret_box.reset_cache()

    gw_settings.apply_overlay()

    import os
    assert os.environ.get("ES_PASSWORD") in (None, "")


def test_unreadable_ciphertext_is_not_clobbered_by_an_unrelated_save(yml, monkeypatch):
    """解不开不等于该删 —— 换错密钥时改别的设置不能把密文抹掉。"""
    gw_settings.save({"es.password": "hunter2"})
    ciphertext = _on_disk(yml)["es.password"]
    from cryptography.fernet import Fernet

    monkeypatch.setenv("RST_SECRET_KEY", Fernet.generate_key().decode())
    secret_box.reset_cache()

    gw_settings.save({"audit.enabled": True})

    assert _on_disk(yml)["es.password"] == ciphertext


def test_write_is_atomic(yml, monkeypatch):
    """写到一半被打断，盘上留的是上一版完整内容，不是半截文件。

    这个文件里是 ES 口令和几个 webhook 凭据。截断之后重启，部署回到「未配置」，
    而界面上没有任何东西说明发生过什么。
    """
    gw_settings.save({"es.url": "http://es-old:9200"})
    good = yml.read_text(encoding="utf-8")

    real_replace = gw_settings.os.replace

    def die(src, dst):
        raise OSError("no space left on device")

    monkeypatch.setattr(gw_settings.os, "replace", die)
    with pytest.raises(OSError):
        gw_settings.save({"es.url": "http://es-new:9200"})
    monkeypatch.setattr(gw_settings.os, "replace", real_replace)

    assert yml.read_text(encoding="utf-8") == good


def test_env_is_not_changed_when_the_write_fails(yml, monkeypatch):
    """盘写失败时进程内也不能已经生效 —— 否则界面说保存成功，重启静默回滚。"""
    import os as _os

    gw_settings.save({"es.url": "http://es-old:9200"})
    assert _os.environ.get("ES_URL") == "http://es-old:9200"

    def die(*a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(gw_settings, "_write_yaml", die)
    with pytest.raises(OSError):
        gw_settings.save({"es.url": "http://es-new:9200"})

    assert _os.environ.get("ES_URL") == "http://es-old:9200"
