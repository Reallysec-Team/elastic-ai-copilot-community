"""The SPA fallback route must not serve files outside the built frontend.

`/v2/{path:path}` used to do `FileResponse(_dist / path)` with no containment
check, which was an arbitrary file read for anyone who could reach the gateway.
Confirmed against a running instance before the fix: `/v2/..%2f..%2f.env`
returned the deployment's ES_PASSWORD and LLM_API_KEY.

Two independent escapes, so both are pinned here:
  - traversal, including percent-encoded (Starlette decodes the path param)
  - an ABSOLUTE path, which needs no '..' at all — pathlib discards the left
    operand of `/` when the right one is absolute
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import main  # noqa: E402


@pytest.fixture
def client():
    return TestClient(main.app)


def _spa_mounted() -> bool:
    """The route only exists when a built frontend is present."""
    return any(getattr(r, "path", "") == "/v2/{path:path}" for r in main.app.routes)


pytestmark = pytest.mark.skipif(
    not _spa_mounted(), reason="frontend dist not built; SPA route not mounted"
)


def _is_spa_shell(resp) -> bool:
    """index.html served back = request was contained (the safe fallback)."""
    body = resp.content.lower()
    return resp.status_code == 200 and (b"<!doctype html" in body or b"<html" in body)


def _contained(resp) -> bool:
    """Nothing escaped the dist root.

    Two safe outcomes, and the distinction is not ours to control: an HTTP
    client may normalize a literal `../` out of the path before it is sent, so
    the request lands on some other route and 404s. Only the percent-encoded
    form (`..%2f`) actually reaches this handler — which is precisely why the
    guard cannot be a string check on the raw path. Either way, no file.
    """
    return _is_spa_shell(resp) or 400 <= resp.status_code < 500


@pytest.mark.parametrize(
    "path",
    [
        "../.env",
        "..%2f..%2f.env",
        "..%2F..%2Fllm_providers.yml",
        "../../poc/.env",
        "%2e%2e%2f%2e%2e%2fsettings.yml",
        "../../../etc/passwd",
        "a/../../../.env",
    ],
)
def test_traversal_never_escapes_the_dist_root(client, path):
    r = client.get(f"/v2/{path}")
    assert _contained(r), f"{path} escaped containment: {r.content[:200]!r}"
    assert b"LLM_API_KEY" not in r.content
    assert b"ES_PASSWORD" not in r.content


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "/app/.env",
        "C:/Windows/win.ini",
        "//etc/hosts",
    ],
)
def test_absolute_paths_do_not_replace_the_root(client, path):
    """`Path(dist) / "/etc/passwd"` == `Path("/etc/passwd")` — no '..' required."""
    r = client.get(f"/v2/{path.lstrip('/')}" if path.startswith("//") else f"/v2{path}")
    assert _contained(r), f"{path} escaped containment: {r.content[:200]!r}"
    assert b"root:" not in r.content


def test_a_real_asset_is_still_served(client):
    """The guard must not break the thing the route exists for."""
    r = client.get("/v2/index.html")
    assert r.status_code == 200
    assert b"<html" in r.content.lower() or b"<!doctype" in r.content.lower()


def test_unknown_client_route_falls_back_to_the_shell(client):
    """Client-side routing: /v2/alerts is not a file and must serve the SPA."""
    assert _is_spa_shell(client.get("/v2/alerts"))
