"""rstlic_storage — pluggable key/value persistence for the RST licensing SDK.

The lifecycle layer (``rstlic_lifecycle.LicenseLifecycle``) needs to persist a
handful of small strings across process restarts: the latest signed token, the
next-heartbeat timestamp, the session secret, etc. WHERE those live is
product-specific:

  * a Splunk app stores them in ``storage/passwords`` (encrypted at rest)
  * a plain backend / CLI / desktop app stores them in a JSON file
  * a test stores them in memory

So the lifecycle depends on this tiny interface instead of any one backend.
All values are plain ``str`` (the lifecycle JSON-encodes anything richer).

Interface (duck-typed — no ABC needed, but :class:`Storage` documents it):

    get(key: str) -> str        # '' when absent
    set(key: str, value: str)   # value or '' to clear
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Callable, Dict, Optional


class Storage:
    """Documentation base class. Any object with ``get``/``set`` works."""

    def get(self, key: str) -> str:  # pragma: no cover - interface doc
        raise NotImplementedError

    def set(self, key: str, value: str) -> None:  # pragma: no cover
        raise NotImplementedError


class MemoryStorage(Storage):
    """In-process dict. For tests and ephemeral runs."""

    def __init__(self) -> None:
        self._d: Dict[str, str] = {}

    def get(self, key: str) -> str:
        return self._d.get(key, '')

    def set(self, key: str, value: str) -> None:
        self._d[key] = value or ''


class FileStorage(Storage):
    """JSON file on disk. The default for non-Splunk products.

    Writes are atomic (temp file + ``os.replace``) so a crash mid-write can't
    corrupt the cache. The file is created lazily on first ``set``.

    Note this is NOT encrypted — the persisted values (signed token, session
    secret) are bearer-ish material. Restrict the file's permissions to the
    service account (``mode=0o600`` by default on POSIX) and/or point ``path``
    at an already-protected directory. For products that have an OS keychain or
    secrets store, wrap that with :class:`CallableStorage` instead.
    """

    def __init__(self, path: str, *, mode: int = 0o600) -> None:
        self._path = path
        self._mode = mode
        self._cache: Optional[Dict[str, str]] = None

    def _load(self) -> Dict[str, str]:
        if self._cache is not None:
            return self._cache
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._cache = {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self._cache = {}
        return self._cache

    def get(self, key: str) -> str:
        return self._load().get(key, '')

    def set(self, key: str, value: str) -> None:
        data = self._load()
        data[key] = value or ''
        directory = os.path.dirname(os.path.abspath(self._path)) or '.'
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix='.rstlic-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f)
            try:
                os.chmod(tmp, self._mode)
            except OSError:
                pass  # chmod unsupported (e.g. Windows) — non-fatal
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


class CallableStorage(Storage):
    """Adapter over two callables — the bridge for hosts with their own store.

    The Splunk adapter wraps ``handler._get_encrypted_credential`` /
    ``handler._store_encrypted_credential`` with this so the lifecycle never
    imports anything Splunk-specific::

        storage = CallableStorage(
            getter=lambda k: handler._get_encrypted_credential(k) or '',
            setter=lambda k, v: handler._store_encrypted_credential(k, v or ''),
        )
    """

    def __init__(self, getter: Callable[[str], Optional[str]],
                 setter: Callable[[str, str], None]) -> None:
        self._getter = getter
        self._setter = setter

    def get(self, key: str) -> str:
        return self._getter(key) or ''

    def set(self, key: str, value: str) -> None:
        self._setter(key, value or '')
