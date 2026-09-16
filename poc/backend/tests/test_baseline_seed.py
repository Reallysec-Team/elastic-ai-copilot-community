"""Auto-seeding the shipped compliance pack.

The 127 rules travel inside the image, but loading them into Elasticsearch was
a manual `python -m scripts.baseline_load_rules` step that no deployment ran —
so the baseline page opened on an empty rule library and read as a broken
feature. Seeding now happens at startup, with one hard constraint: a library
someone has curated must never grow back.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.baseline import store  # noqa: E402


class FakeIndices:
    def __init__(self, exists: bool):
        self._exists = exists

    async def exists(self, index):
        return self._exists


class FakeResp:
    def __init__(self, body):
        self.body = body


class FakeES:
    """Minimal ES double: existence, count, bulk."""

    def __init__(self, *, exists: bool, count: int, bulk_errors: int = 0):
        self.indices = FakeIndices(exists)
        self._count = count
        self._bulk_errors = bulk_errors
        self.bulk_ops = None

    async def count(self, index):
        return FakeResp({"count": self._count})

    async def bulk(self, operations, refresh=False):
        self.bulk_ops = operations
        n_docs = len(operations) // 2
        items = [{"index": {"status": 201}} for _ in range(n_docs)]
        for i in range(min(self._bulk_errors, n_docs)):
            items[i] = {"index": {"error": {"type": "mapper_parsing_exception"}}}
        return FakeResp({"items": items})


@pytest.fixture
def es(monkeypatch):
    made = {}

    def install(**kw):
        e = FakeES(**kw)
        made["es"] = e
        monkeypatch.setattr(store, "get_es", lambda: e)
        return e

    install.made = made
    return install


@pytest.mark.asyncio
async def test_seeds_the_full_pack_into_a_missing_index(es):
    e = es(exists=False, count=0)
    n = await store.seed_bundled_rules_if_empty()
    assert n == 127, "the shipped pack is 127 rules"
    # doc id must be the rule_id so re-seeding is idempotent, never duplicating.
    ids = [op["index"]["_id"] for op in e.bulk_ops[0::2]]
    assert len(ids) == len(set(ids)) == 127
    assert all(op["index"]["_index"] == store.RULES_INDEX for op in e.bulk_ops[0::2])


@pytest.mark.asyncio
async def test_seeds_an_existing_but_empty_index(es):
    es(exists=True, count=0)
    assert await store.seed_bundled_rules_if_empty() == 127


@pytest.mark.asyncio
async def test_never_regrows_a_curated_library(es):
    """THE constraint. Someone deleted the rules that don't apply to their
    estate; a restart must not undo that."""
    e = es(exists=True, count=27)
    assert await store.seed_bundled_rules_if_empty() == 0
    assert e.bulk_ops is None, "must not write at all"


@pytest.mark.asyncio
async def test_seeded_docs_carry_what_the_baseline_engine_reads(es):
    e = es(exists=False, count=0)
    await store.seed_bundled_rules_if_empty()
    doc = e.bulk_ops[1]
    for field in ("rule_id", "title", "category", "platform", "severity",
                  "collect", "judge", "enabled", "created_at", "updated_at"):
        assert field in doc, f"seeded doc is missing {field}"
    assert doc["enabled"] is True
    assert doc["collect"]["query_name"], "query_name backstops to rule_id"
    assert set(doc["judge"]) >= {"operator", "field", "expected", "on_missing"}


@pytest.mark.asyncio
async def test_es_failure_does_not_propagate(es, monkeypatch):
    """Seeding is best-effort — it runs in the startup path and must never stop
    the gateway from coming up."""
    class Boom:
        indices = FakeIndices(False)

        async def bulk(self, *a, **kw):
            raise RuntimeError("ES is down")

    monkeypatch.setattr(store, "get_es", lambda: Boom())
    assert await store.seed_bundled_rules_if_empty() == 0


@pytest.mark.asyncio
async def test_missing_source_file_is_survivable(es, tmp_path):
    es(exists=False, count=0)
    assert await store.seed_bundled_rules_if_empty(str(tmp_path / "nope.json")) == 0


@pytest.mark.asyncio
async def test_partial_bulk_failure_is_counted_honestly(es):
    e = es(exists=False, count=0, bulk_errors=5)
    assert await store.seed_bundled_rules_if_empty() == 122
    assert e.bulk_ops is not None


def test_the_bundled_pack_is_present_and_well_formed():
    """Guards the release artifact itself: the pack must ship inside the image
    next to the code that loads it."""
    p = Path(store._BUNDLED_RULES)
    assert p.exists(), f"shipped rule pack missing at {p}"
    data = json.loads(p.read_text(encoding="utf-8"))
    rules = data.get("rules") if isinstance(data, dict) else data
    assert len(rules) == 127
    assert all(r.get("rule_id") for r in rules), "every rule needs a stable id"
