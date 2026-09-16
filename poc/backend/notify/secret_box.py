"""Symmetric encryption for stored secrets (Feishu bot secrets, webhook HMAC keys).

Fernet (AES-128-CBC + HMAC) with a key resolved once, in priority order:
  1. env ``RST_SECRET_KEY``      — a urlsafe-base64 32-byte Fernet key
  2. key file ``RST_SECRET_KEY_FILE`` (default ``./.rst_secret_key``) — auto-created

Auto-creating a persisted key means secrets survive restarts out-of-box without
operator setup, yet never live in plaintext inside ``settings.yml`` / ES. Rotating
the key invalidates existing ciphertext (operators must re-enter secrets) — an
acceptable, documented ceiling for a single-key scheme.

「持久化」取决于那个路径落在哪儿：默认值是相对 CWD 的 ``./.rst_secret_key``，在
容器里就是镜像层，**升级一次镜像就换一把新钥匙** —— 飞书和钉钉的签名密钥、SMTP
密码会一起变成解不开的密文，现象是升级后投递突然签名不符 / 认证失败，看不出原因。
compose 因此把 ``RST_SECRET_KEY_FILE`` 指到 state 卷；下面的迁移负责把老部署留在
镜像层里的那把钥匙带过去。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("rst.notify.secret_box")

_DEFAULT_KEY_FILE = ".rst_secret_key"
_fernet: Fernet | None = None


def _load_or_create_key() -> bytes:
    env_key = (os.environ.get("RST_SECRET_KEY") or "").strip()
    if env_key:
        return env_key.encode()
    path = Path(os.environ.get("RST_SECRET_KEY_FILE", _DEFAULT_KEY_FILE))
    if path.exists():
        return path.read_bytes().strip()
    # 老部署的钥匙在默认路径（镜像层）。换到持久化路径时要带过去，否则升级完
    # 所有已保存的密钥都解不开，而界面上只会显示「已设置密钥」—— 看上去一切正常。
    legacy = Path(_DEFAULT_KEY_FILE)
    if path != legacy and legacy.exists():
        key = legacy.read_bytes().strip()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(key)
            try:
                path.chmod(0o600)
            except OSError:
                pass
            logger.warning("secret_key_migrated", extra={"from": str(legacy), "to": str(path)})
        except OSError as e:
            logger.warning("secret_key_migrate_failed", extra={"error": str(e)})
        return key
    key = Fernet.generate_key()
    try:
        path.write_bytes(key)
        try:  # best-effort tighten perms (no-op on Windows)
            path.chmod(0o600)
        except OSError:
            pass
        logger.warning("secret_key_generated", extra={"path": str(path)})
    except OSError as e:
        logger.warning("secret_key_persist_failed", extra={"error": str(e)})
    return key


def _box() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def reset_cache() -> None:
    """Drop the cached Fernet (after RST_SECRET_KEY changes at runtime)."""
    global _fernet
    _fernet = None


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _box().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt; return "" on empty/garbled input rather than raising, so a
    rotated key degrades to "secret missing" (delivery unsigned) not a crash."""
    if not token:
        return ""
    try:
        return _box().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError) as e:
        logger.warning("secret_decrypt_failed", extra={"error": str(e)})
        return ""


def is_stale(token: str) -> bool:
    """A ciphertext exists but this gateway's key can't open it — the state
    volume (and .rst_secret_key) was replaced while the config lived on in ES.
    Reported to the UI so the operator re-enters the value instead of
    discovering it from a failed delivery."""
    if not token:
        return False
    try:
        _box().decrypt(token.encode())
        return False
    except (InvalidToken, ValueError):
        return True
