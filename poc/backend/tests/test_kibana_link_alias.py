"""Backing-index -> alias resolution for Kibana deep links.

Kibana's alerts-as-data indices are written through an alias. A search hit
reports the concrete backing index behind it (`.internal.<alias>-000015`), a
name that changes on every rollover and that nobody creates a data view
against. Resolving it literally makes Discover links break silently the first
time the alias rolls over.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import kibana_link as kl  # noqa: E402


def _resolve(index: str) -> str:
    """Drive the async resolver without depending on pytest-asyncio."""
    return asyncio.run(kl.resolve_data_view_id(index))

ALIAS = ".alerts-security.alerts-default"
BACKING = ".internal.alerts-security.alerts-default-000015"


@pytest.fixture(autouse=True)
def _clear_cache():
    kl._DATA_VIEW_CACHE.clear()
    yield
    kl._DATA_VIEW_CACHE.clear()


class TestAliasOfBackingIndex:
    def test_recognizes_a_kibana_backing_index(self):
        assert kl.alias_of_backing_index(BACKING) == ALIAS

    def test_handles_other_alerts_spaces(self):
        assert (
            kl.alias_of_backing_index(".internal.alerts-observability.logs.alerts-default-000001")
            == ".alerts-observability.logs.alerts-default"
        )

    @pytest.mark.parametrize(
        "index",
        [
            ALIAS,                      # already the alias
            "logs-system.security",     # ordinary index
            ".ds-logs-generic-000004",  # data stream backing index, not .internal.
            ".internal.alerts-no-suffix",
            "",
        ],
    )
    def test_leaves_everything_else_alone(self, index):
        assert kl.alias_of_backing_index(index) is None


class TestResolveFallsBackToAlias:
    """A backing index that has no data view resolves under its alias."""

    def _stub(self, monkeypatch, known: dict[str, str]):
        seen: list[str] = []

        async def fake_find(index: str) -> str:
            seen.append(index)
            if index in known:
                return known[index]
            raise kl.DataViewNotFound(f"no data view for {index}")

        monkeypatch.setattr(kl, "_find_data_view_id", fake_find)
        return seen

    def test_backing_index_resolves_via_alias(self, monkeypatch):
        seen = self._stub(monkeypatch, {ALIAS: "dv-1"})
        assert _resolve(BACKING) == "dv-1"
        # Tried the literal name first, then the alias.
        assert seen == [BACKING, ALIAS]

    def test_result_is_cached_under_the_original_name(self, monkeypatch):
        """Alerts already stored with a backing-index name must not pay the
        double lookup on every open."""
        seen = self._stub(monkeypatch, {ALIAS: "dv-1"})
        _resolve(BACKING)
        _resolve(BACKING)
        assert seen == [BACKING, ALIAS]  # second call served from cache

    def test_a_data_view_on_the_backing_index_still_wins(self, monkeypatch):
        seen = self._stub(monkeypatch, {BACKING: "dv-exact", ALIAS: "dv-alias"})
        assert _resolve(BACKING) == "dv-exact"
        assert seen == [BACKING]  # no pointless alias lookup

    def test_error_names_the_alias_when_neither_exists(self, monkeypatch):
        """The operator should be told to create the STABLE name, not the
        rollover-scoped one."""
        self._stub(monkeypatch, {})
        with pytest.raises(kl.DataViewNotFound) as e:
            _resolve(BACKING)
        assert ALIAS in str(e.value)

    def test_ordinary_index_is_unaffected(self, monkeypatch):
        seen = self._stub(monkeypatch, {"logs-app": "dv-2"})
        assert _resolve("logs-app") == "dv-2"
        assert seen == ["logs-app"]
