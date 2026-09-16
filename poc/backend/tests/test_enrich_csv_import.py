"""CSV import security boundary: column whitelist, size/row caps, string-only,
normalized keys, validate-all-then-index."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.enrich import csv_import  # noqa: E402


class FakeES:
    def __init__(self):
        self.docs = []

    async def bulk(self, operations=None, **kw):
        # operations alternate action/doc; count the docs
        self.docs.extend(operations[1::2])
        return {"errors": False, "items": []}


@pytest.mark.asyncio
async def test_assets_import_normalizes_host_keys():
    es = FakeES()
    csv = "name,host,criticality\n财务DB-01,WIN-DB01.corp.local,high\n"
    r = await csv_import.import_csv(csv, "assets", es)
    assert r["indexed"] == 1
    assert r["index"] == csv_import.csv_source.ASSETS_INDEX
    doc = es.docs[0]
    assert set(doc["keys"]) == {"win-db01.corp.local", "win-db01"}
    assert doc["name"] == "财务DB-01"


@pytest.mark.asyncio
async def test_identities_import_normalizes_user_key():
    es = FakeES()
    csv = "name,user,department\n张三,CORP\\jsmith,财务部\n"
    r = await csv_import.import_csv(csv, "identities", es)
    assert es.docs[0]["user_key"] == "jsmith"


@pytest.mark.asyncio
async def test_unknown_column_rejected():
    with pytest.raises(csv_import.CsvImportError) as e:
        await csv_import.import_csv("name,evil\na,b\n", "assets", FakeES())
    assert "evil" in str(e.value)


@pytest.mark.asyncio
async def test_oversize_rejected():
    with pytest.raises(csv_import.CsvImportError):
        await csv_import.import_csv("a" * (csv_import.MAX_BYTES + 1), "assets", FakeES())


@pytest.mark.asyncio
async def test_too_many_rows_rejected(monkeypatch):
    monkeypatch.setattr(csv_import, "MAX_ROWS", 2)
    csv = "name,host\n" + "a,b\n" * 3
    with pytest.raises(csv_import.CsvImportError):
        await csv_import.import_csv(csv, "assets", FakeES())


@pytest.mark.asyncio
async def test_bad_kind_rejected():
    with pytest.raises(csv_import.CsvImportError):
        await csv_import.import_csv("name\na\n", "bogus", FakeES())


@pytest.mark.asyncio
async def test_no_write_when_validation_fails():
    es = FakeES()
    # second row has an unknown column count won't trigger; force a whitelist fail
    with pytest.raises(csv_import.CsvImportError):
        await csv_import.import_csv("name,evil\na,b\n", "assets", es)
    assert es.docs == []  # nothing indexed


@pytest.mark.asyncio
async def test_bulk_partial_failure_raises():
    class ErrES:
        async def bulk(self, operations=None, **kw):
            return {"errors": True, "items": [{"index": {"status": 400}}]}
    with pytest.raises(csv_import.CsvImportError):
        await csv_import.import_csv("name,host\n财务DB-01,win-db01\n", "assets", ErrES())


@pytest.mark.asyncio
async def test_reimport_uses_stable_id_for_assets():
    class IdES:
        def __init__(self): self.ids = []
        async def bulk(self, operations=None, **kw):
            self.ids += [op["index"]["_id"] for op in operations[0::2]]
            return {"errors": False}
    csv = "name,host,ip\n财务DB-01,WIN-DB01.corp.local,203.0.113.5\n"
    es1, es2 = IdES(), IdES()
    await csv_import.import_csv(csv, "assets", es1)
    await csv_import.import_csv(csv, "assets", es2)
    assert es1.ids == es2.ids            # same input → same _id (upsert, not duplicate)
    assert len(es1.ids) == 1


@pytest.mark.asyncio
async def test_distinct_assets_get_distinct_ids():
    class IdES:
        def __init__(self): self.ids = []
        async def bulk(self, operations=None, **kw):
            self.ids += [op["index"]["_id"] for op in operations[0::2]]
            return {"errors": False}
    csv = "name,host\nA,host-a\nB,host-b\n"
    es = IdES()
    await csv_import.import_csv(csv, "assets", es)
    assert len(set(es.ids)) == 2


@pytest.mark.asyncio
async def test_identity_stable_id():
    class IdES:
        def __init__(self): self.ids = []
        async def bulk(self, operations=None, **kw):
            self.ids += [op["index"]["_id"] for op in operations[0::2]]
            return {"errors": False}
    csv = "name,user\n张三,CORP\\jsmith\n"
    es1, es2 = IdES(), IdES()
    await csv_import.import_csv(csv, "identities", es1)
    await csv_import.import_csv(csv, "identities", es2)
    assert es1.ids == es2.ids and len(es1.ids) == 1
