"""Stage 1 — Provider.kind → client factory dispatch.

Verifies the provider gains a `kind` (and Azure-oriented `api_version`) field,
that `_get_client` dispatches on it, unknown kinds fail loud, and the YAML
loader + status() surface the new field. Pure unit test — no real LLM/network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from openai import AsyncAzureOpenAI, AsyncOpenAI  # noqa: E402

from backend import llm_router  # noqa: E402
from backend.llm_router import LLMRouter, Provider  # noqa: E402


def _p(**over):
    base = dict(id="p", base_url="http://x", api_key="k", model="m")
    base.update(over)
    return Provider(**base)


def test_provider_defaults_to_openai_kind():
    p = _p()
    assert p.kind == "openai"
    assert p.api_version == ""


def test_get_client_openai_kind_returns_asyncopenai():
    r = LLMRouter([_p()])
    assert isinstance(r._get_client(_p()), AsyncOpenAI)


def test_get_client_unknown_kind_raises():
    r = LLMRouter([_p(kind="martian")])
    with pytest.raises(ValueError, match="martian"):
        r._get_client(_p(kind="martian"))


def test_get_client_is_cached():
    r = LLMRouter([_p()])
    p = _p()
    assert r._get_client(p) is r._get_client(p)


def test_from_yaml_reads_kind_and_api_version(tmp_path):
    cfg = tmp_path / "llm.yml"
    cfg.write_text(
        "providers:\n"
        "  - id: az\n"
        "    kind: azure\n"
        "    base_url: https://x.openai.azure.com\n"
        "    api_key: k\n"
        "    model: gpt-4o\n"
        "    api_version: '2024-06-01'\n",
        encoding="utf-8",
    )
    r = llm_router._from_yaml(cfg)
    assert len(r.providers) == 1
    assert r.providers[0].kind == "azure"
    assert r.providers[0].api_version == "2024-06-01"


def test_from_yaml_defaults_kind_openai(tmp_path):
    cfg = tmp_path / "llm.yml"
    cfg.write_text(
        "providers:\n"
        "  - id: oa\n"
        "    base_url: http://x\n"
        "    api_key: k\n"
        "    model: m\n",
        encoding="utf-8",
    )
    r = llm_router._from_yaml(cfg)
    assert r.providers[0].kind == "openai"


def test_status_exposes_kind():
    r = LLMRouter([_p(kind="openai")])
    assert r.status()["providers"][0]["kind"] == "openai"


# --- Stage 2: Azure OpenAI --------------------------------------------------

def _az(**over):
    base = dict(
        id="az",
        kind="azure",
        base_url="https://x.openai.azure.com",
        api_key="k",
        model="gpt-4o",
        api_version="2024-06-01",
    )
    base.update(over)
    return Provider(**base)


def test_build_client_azure_returns_asyncazureopenai():
    r = LLMRouter([_az()])
    assert isinstance(r._get_client(_az()), AsyncAzureOpenAI)


def test_azure_client_uses_endpoint_and_api_version():
    r = LLMRouter([_az()])
    c = r._get_client(_az())
    # AsyncAzureOpenAI stitches endpoint + api-version into base_url.
    assert "x.openai.azure.com" in str(c.base_url)
    assert c._api_version == "2024-06-01"


def test_azure_missing_api_version_raises():
    r = LLMRouter([_az(api_version="")])
    with pytest.raises(ValueError, match="api_version"):
        r._get_client(_az(api_version=""))


def test_azure_and_openai_clients_are_distinct():
    r = LLMRouter([_p(), _az()])
    assert not isinstance(r._get_client(_p()), AsyncAzureOpenAI)
    assert isinstance(r._get_client(_az()), AsyncAzureOpenAI)


def test_save_providers_persists_kind_and_api_version(tmp_path, monkeypatch):
    cfg = tmp_path / "llm.yml"
    monkeypatch.setenv("RST_LLM_CONFIG", str(cfg))
    llm_router.reset()
    llm_router.save_providers([{
        "id": "az",
        "kind": "azure",
        "base_url": "https://x.openai.azure.com",
        "api_key": "k",
        "model": "gpt-4o",
        "api_version": "2024-06-01",
    }])
    r = llm_router._from_yaml(cfg)
    assert r.providers[0].kind == "azure"
    assert r.providers[0].api_version == "2024-06-01"


def test_save_providers_azure_without_api_version_rejected(tmp_path, monkeypatch):
    cfg = tmp_path / "llm.yml"
    monkeypatch.setenv("RST_LLM_CONFIG", str(cfg))
    llm_router.reset()
    with pytest.raises(ValueError, match="api_version"):
        llm_router.save_providers([{
            "id": "az",
            "kind": "azure",
            "base_url": "https://x.openai.azure.com",
            "api_key": "k",
            "model": "gpt-4o",
        }])
