"""Notify config: validation, redaction, severity ranking, secret box."""
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.notify import config as cfg  # noqa: E402
from backend.notify import secret_box  # noqa: E402


# ---- secret_box ----------------------------------------------------------

@pytest.fixture
def fresh_key(monkeypatch):
    monkeypatch.setenv("RST_SECRET_KEY", Fernet.generate_key().decode())
    secret_box.reset_cache()
    yield
    secret_box.reset_cache()


def test_encrypt_decrypt_round_trip(fresh_key):
    token = secret_box.encrypt("hunter2")
    assert token and token != "hunter2"
    assert secret_box.decrypt(token) == "hunter2"


def test_encrypt_empty_is_empty(fresh_key):
    assert secret_box.encrypt("") == ""
    assert secret_box.decrypt("") == ""


def test_decrypt_garbage_returns_empty(fresh_key):
    assert secret_box.decrypt("not-a-valid-token") == ""


def test_decrypt_with_rotated_key_returns_empty(monkeypatch):
    monkeypatch.setenv("RST_SECRET_KEY", Fernet.generate_key().decode())
    secret_box.reset_cache()
    token = secret_box.encrypt("secret")
    # rotate the key → old ciphertext no longer decryptable, degrades to ""
    monkeypatch.setenv("RST_SECRET_KEY", Fernet.generate_key().decode())
    secret_box.reset_cache()
    assert secret_box.decrypt(token) == ""


# ---- severity ranking ----------------------------------------------------

def test_sev_rank_orders():
    assert cfg.sev_rank("info") < cfg.sev_rank("high") < cfg.sev_rank("critical")


def test_sev_rank_unknown_defaults_to_threshold():
    assert cfg.sev_rank("bogus") == cfg.sev_rank("high")
    assert cfg.sev_rank(None) == cfg.sev_rank("high")


# ---- validation ----------------------------------------------------------

def test_validate_periods_good():
    assert cfg._validate_periods(["daily", "weekly", "daily"]) == ["daily", "weekly"]


@pytest.mark.parametrize("bad", [["hourly"], "daily", [123]])
def test_validate_periods_bad(bad):
    with pytest.raises(ValueError):
        cfg._validate_periods(bad)


def _good_target(**over):
    t = {
        "name": "SOC 群",
        "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/abc",
        "periods": ["daily"],
        "alert_severity_threshold": "high",
    }
    t.update(over)
    return t


def test_validate_target_ok():
    cfg._validate_target_input(_good_target())


def test_validate_target_blank_name():
    with pytest.raises(ValueError, match="name"):
        cfg._validate_target_input(_good_target(name="  "))


def test_validate_target_bad_url():
    with pytest.raises(ValueError):
        cfg._validate_target_input(_good_target(webhook_url="https://evil.com/x"))


def test_validate_target_bad_threshold():
    with pytest.raises(ValueError, match="threshold"):
        cfg._validate_target_input(_good_target(alert_severity_threshold="doom"))


# ---- redaction -----------------------------------------------------------

def test_redact_strips_secret_and_flags_presence():
    r = cfg._redact_target({"id": "t1", "name": "x", "secret_enc": "cipher"})
    assert "secret_enc" not in r
    assert r["secret_set"] is True


def test_redact_no_secret():
    r = cfg._redact_target({"id": "t1", "name": "x", "secret_enc": ""})
    assert r["secret_set"] is False


# ---- 密钥文件的位置（升级不能把密钥弄丢） -----------------------------------


def test_secret_key_migrates_from_the_legacy_path(tmp_path, monkeypatch):
    """老部署的钥匙在相对 CWD 的默认路径 —— 容器里那是镜像层，升级即丢失。
    换到持久化路径时必须带过去，否则升级完所有已保存的密钥都解不开，而界面上
    还显示着「已设置密钥」，看上去一切正常。"""
    from cryptography.fernet import Fernet

    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / secret_box._DEFAULT_KEY_FILE
    key = Fernet.generate_key()
    legacy.write_bytes(key)

    target = tmp_path / "state" / ".rst_secret_key"
    monkeypatch.delenv("RST_SECRET_KEY", raising=False)
    monkeypatch.setenv("RST_SECRET_KEY_FILE", str(target))
    secret_box.reset_cache()

    assert secret_box._load_or_create_key() == key
    assert target.exists(), "钥匙要落到持久化路径上，否则下次还是要迁一遍"
    secret_box.reset_cache()


def test_secret_survives_the_move(tmp_path, monkeypatch):
    """真正要保的是这个：搬完之后，搬之前加密的东西还解得开。"""
    from cryptography.fernet import Fernet

    monkeypatch.chdir(tmp_path)
    (tmp_path / secret_box._DEFAULT_KEY_FILE).write_bytes(Fernet.generate_key())
    monkeypatch.delenv("RST_SECRET_KEY", raising=False)
    secret_box.reset_cache()
    token = secret_box.encrypt("SECdemo")

    monkeypatch.setenv("RST_SECRET_KEY_FILE", str(tmp_path / "state" / ".rst_secret_key"))
    secret_box.reset_cache()
    assert secret_box.decrypt(token) == "SECdemo"
    secret_box.reset_cache()
