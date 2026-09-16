"""In-process pub/sub for the real-time alert SSE stream.

Each SSE client subscribes a bounded queue; producers (poll tail + webhook)
publish normalized alerts to every subscriber. Bounded + drop-oldest so a slow
client can't grow memory without limit. Single-process only — with multiple
gateway replicas each streams the alerts it ingested (acceptable: the poll tail
runs per-replica; webhook source hits one replica). Cross-replica fan-out would
need Redis pub/sub, deferred.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("rst.alerts.broker")

_MAX_QUEUE = 100
_subscribers: set[asyncio.Queue] = set()


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def publish(alert: dict[str, Any]) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(alert)
        except asyncio.QueueFull:
            # Drop the oldest to make room — a live tail beats a stalled one.
            try:
                q.get_nowait()
                q.put_nowait(alert)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

