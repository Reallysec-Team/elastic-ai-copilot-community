"""The index picker must not offer the product's own storage.

`baseline-rules` holds compliance rule definitions (`judge`,
`remediation_template`, `standard_refs`) and carries no log fields at all.
Offering it as a target for "generate a detection rule" produces a correct but
baffling refusal — the model is asked to find `event.action` in a rule
catalogue — and the operator reads that as the product being broken. Most of
the product's storage is dot-prefixed and hidden already; the baseline pack's
is not, which is exactly why this needs a test rather than a convention.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import owned_indices  # noqa: E402


def test_the_non_dotted_product_indices_are_listed():
    """These are the ones the '.'-prefix filter cannot catch."""
    names = owned_indices.owned_index_names()
    for n in ("baseline-rules", "baseline-results", "baseline-runs", "eol-catalog"):
        assert n in names, f"{n} would leak into the index picker"


def test_the_dotted_product_indices_are_listed_too():
    """Belt and braces: if the '.' convention ever changes, these stay hidden."""
    names = owned_indices.owned_index_names()
    for n in (".rst_copilot_alerts", ".rst_copilot_analysis", ".rst_copilot_audit",
              ".rst_copilot_conversations", ".rst_copilot_userstate"):
        assert n in names


def test_customer_owned_sources_are_not_claimed(monkeypatch):
    """Sources the product only READS must stay pickable — hiding the customer's
    own alert index would break the feature that ingests from it."""
    monkeypatch.setenv("RST_ALERT_INGEST_INDEX", ".alerts-security.alerts-default")
    names = owned_indices.owned_index_names()
    assert ".alerts-security.alerts-default" not in names
    assert not any("osquery" in n for n in names)
    assert "kibana_sample_data_logs" not in names


def test_renaming_via_env_keeps_the_list_correct(monkeypatch):
    """The list is derived from the same resolvers the writers use, so a rename
    cannot leave a stale name behind."""
    monkeypatch.setenv("RST_ANALYSIS_INDEX", "custom-analysis-idx")
    names = owned_indices.owned_index_names()
    assert "custom-analysis-idx" in names
    assert ".rst_copilot_analysis" not in names


def test_never_raises_on_a_broken_resolver(monkeypatch):
    """A resolver blowing up must not take the index picker down with it."""
    from backend import analysis_store

    def boom():
        raise RuntimeError("nope")

    monkeypatch.setattr(analysis_store, "_index", boom)
    names = owned_indices.owned_index_names()
    assert isinstance(names, set)
    assert "baseline-rules" in names  # the rest still resolve
