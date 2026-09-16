"""内存模式下，列表和单条读对「过期」的定义必须一致：列表里出现的会话点开不能 404。"""
import asyncio
import sys
import time
from pathlib import Path

_POC = Path(__file__).resolve().parent.parent.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

from backend import conversation  # noqa: E402


def test_mem_list_hides_expired_entries(monkeypatch):
    monkeypatch.delenv("RST_CONVERSATION_BACKEND", raising=False)
    conversation._store.clear()

    async def run():
        fresh_id, _ = await conversation.get_or_create(None, owner=None)
        stale_id, _ = await conversation.get_or_create(None, owner=None)
        # 手动把一条推到 TTL 之外
        conversation._store[stale_id]["last_at"] = time.time() - conversation.TTL_SECONDS - 1
        listed = await conversation.list_all(limit=10, offset=0, owner=None)
        ids = {c["id"] for c in listed["conversations"]}
        assert fresh_id in ids
        assert stale_id not in ids
        # 列表里有的都能读到
        for cid in ids:
            assert await conversation.get(cid, owner=None) is not None

    asyncio.run(run())
