"""Every documented .env key must actually reach the container.

docker compose reads `.env` for INTERPOLATION ONLY. A variable reaches the
gateway process only if it is named in the service's `environment:` block.
Thirteen keys were documented in `.env.example`, read by shipped code, and
absent from the compose env block — so an operator could set `LLM_TIMEOUT_S`,
watch `docker compose config` resolve it (it IS in .env), restart, and see no
change, with nothing anywhere to explain why. `RST_EMBED_*` being in that set
meant the RAG knowledge base could never work on any deployment.

This test compares the two files directly, because the failure is silent in
both directions and no runtime check can catch it.
"""
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_ROOT))

ENV_EXAMPLE = _ROOT / ".env.example"
PROD_COMPOSE = _ROOT / "docker-compose.prod.yml"
OTHER_COMPOSE = (_ROOT / "docker-compose.yml", _ROOT / "docker-compose.sso.yml")

# Keys that legitimately live only in .env.example: consumed by the host-side
# tooling (compose interpolation, deploy.sh, Caddy) rather than by the gateway.
_NOT_GATEWAY_ENV = {
    "GATEWAY_IMAGE_TAG",      # selects the image; compose-level by definition
    "RST_GATEWAY_CPUS",       # deploy.resources limits
    "RST_GATEWAY_MEM",
    "CADDY_SITE_ADDRESS",     # caddy service
    "CADDY_BASIC_AUTH_USER",
    "CADDY_BASIC_AUTH_HASH",
    "RST_SSO_ENABLED",        # documented for reference; set by the SSO compose
    "RST_SSO_ENFORCE",
    "RST_USER_DB_USER",       # userdb service credentials; the gateway sees
    "RST_USER_DB_PASSWORD",   # only the assembled RST_USER_DB_URL
    "RST_USER_DB_NAME",
}


def _documented_keys() -> set[str]:
    """Uncommented KEY= lines in .env.example — what we tell operators to set."""
    out = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]*)=", line.strip())
        if m:
            out.add(m.group(1))
    return out


def _commented_keys() -> set[str]:
    """`# KEY=value` lines — optional knobs we still tell operators about, so
    they must pass through too or setting them does nothing."""
    out = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^#\s*([A-Z][A-Z0-9_]{2,})=", line.strip())
        if m:
            out.add(m.group(1))
    return out


def _compose_env_keys(path: Path) -> set[str]:
    """Names on the left of `- KEY=` inside the compose file."""
    return set(re.findall(r"^\s*-\s+([A-Z][A-Z0-9_]*)=", path.read_text(encoding="utf-8"), re.M))


@pytest.mark.skipif(not ENV_EXAMPLE.exists() or not PROD_COMPOSE.exists(),
                    reason="run from a full checkout")
def test_every_documented_key_reaches_the_gateway():
    documented = (_documented_keys() | _commented_keys()) - _NOT_GATEWAY_ENV
    passed = _compose_env_keys(PROD_COMPOSE)
    missing = sorted(documented - passed)
    assert not missing, (
        "documented in .env.example but never passed into the container — "
        f"setting these does nothing: {missing}"
    )


@pytest.mark.skipif(not PROD_COMPOSE.exists(), reason="run from a full checkout")
def test_the_keys_the_rag_knowledge_base_needs_are_passed():
    """Regression pin: their absence made /api/kb/* dead on every install."""
    passed = _compose_env_keys(PROD_COMPOSE)
    for k in ("RST_EMBED_MODEL", "RST_EMBED_BASE_URL", "RST_EMBED_DIM"):
        assert k in passed


@pytest.mark.parametrize("path", OTHER_COMPOSE, ids=lambda p: p.name)
@pytest.mark.skipif(not PROD_COMPOSE.exists(), reason="run from a full checkout")
def test_the_other_compose_files_read_dot_env_wholesale(path: Path):
    """dev/sso list only their own overrides — the rest must come from `.env`.

    Their `environment:` blocks were each ~50 keys behind prod (the baseline
    index names among them), so an operator following `.env.example` on an SSO
    deployment set values that never reached the process, silently. Rather than
    keep three hand-copied lists in sync, both files pull `.env` in whole; prod
    keeps its explicit list because that one is the delivery contract.
    """
    text = path.read_text(encoding="utf-8")
    assert re.search(r"^\s*env_file:\s*$", text, re.M), f"{path.name} lost its env_file block"
    assert re.search(r"^\s*-\s*path:\s*\.env\s*$", text, re.M), f"{path.name} must read .env"
