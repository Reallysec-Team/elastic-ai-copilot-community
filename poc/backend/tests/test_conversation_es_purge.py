"""ES 模式：列表顺手清过期文档，一小时最多一次；清理失败不影响列表。"""
import asyncio
import sys
import time
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

import pytest  # noqa: E402

from backend import conversation  # noqa: E402


class _FakeES:
    def __init__(self, fail_purge: bool = False):
        self.searched: list[dict] = []
        self.purged: list[dict] = []
        self.fail_purge = fail_purge

    class _Body:
        def __init__(self, body):
            self.body = body

    async def search(self, index, body):  # noqa: A002
        self.searched.append(body)
        return self._Body({"hits": {"total": {"value": 0}, "hits": []}})

    async def delete_by_query(self, index, query, conflicts):  # noqa: A002
        if self.fail_purge:
            raise RuntimeError("boom")
        self.purged.append(query)
        return self._Body({"deleted": 3})


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    conversation._reset_purge_for_tests()
    monkeypatch.setenv("RST_CONVERSATION_TTL_DAYS", "7")
    yield
    conversation._reset_purge_for_tests()


def _wire(monkeypatch, es):
    monkeypatch.setattr(conversation, "get_es", lambda: es, raising=False)
    monkeypatch.setattr("backend.es_client.get_es", lambda: es)


def test_list_purges_once_per_hour(monkeypatch):
    es = _FakeES()
    _wire(monkeypatch, es)
    asyncio.run(conversation._es_list_all(10, 0, owner=None))
    asyncio.run(conversation._es_list_all(10, 0, owner=None))
    assert len(es.purged) == 1
    lt = es.purged[0]["range"]["last_at"]["lt"]
    assert abs((time.time() - 7 * 86400) - lt) < 5
    assert len(es.searched) == 2


def test_purge_failure_does_not_break_listing(monkeypatch):
    es = _FakeES(fail_purge=True)
    _wire(monkeypatch, es)
    out = asyncio.run(conversation._es_list_all(10, 0, owner=None))
    assert out == {"total": 0, "conversations": []}
    assert len(es.searched) == 1
