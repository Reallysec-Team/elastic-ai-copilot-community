"""Auth resolution for server-side Kibana saved_objects calls.

Regression: a secured customer Kibana 401'd because the call sent no
credentials. `_kibana_auth` must reuse ES creds by default and honor the
Kibana-specific overrides in priority order.
"""

import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import kibana_link  # noqa: E402


_KEYS = [
    "KIBANA_API_KEY",
    "KIBANA_USER",
    "KIBANA_PASSWORD",
    "ES_USER",
    "ES_PASSWORD",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in _KEYS:
        monkeypatch.delenv(k, raising=False)
    yield


def test_no_creds_returns_none(monkeypatch):
    assert kibana_link._kibana_auth() == ({}, None)


def test_reuses_es_creds(monkeypatch):
    monkeypatch.setenv("ES_USER", "elastic")
    monkeypatch.setenv("ES_PASSWORD", "pw")
    headers, auth = kibana_link._kibana_auth()
    assert headers == {}
    assert auth == ("elastic", "pw")


def test_kibana_user_overrides_es(monkeypatch):
    monkeypatch.setenv("ES_USER", "elastic")
    monkeypatch.setenv("ES_PASSWORD", "pw")
    monkeypatch.setenv("KIBANA_USER", "kib")
    monkeypatch.setenv("KIBANA_PASSWORD", "kpw")
    assert kibana_link._kibana_auth() == ({}, ("kib", "kpw"))


def test_api_key_wins(monkeypatch):
    monkeypatch.setenv("ES_USER", "elastic")
    monkeypatch.setenv("ES_PASSWORD", "pw")
    monkeypatch.setenv("KIBANA_API_KEY", "abc123")
    headers, auth = kibana_link._kibana_auth()
    assert headers == {"Authorization": "ApiKey abc123"}
    assert auth is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
