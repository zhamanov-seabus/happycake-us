"""In-memory pub/sub for order status events.

Subscribers (SSE clients) call `subscribe(order_id)` to get an asyncio.Queue.
Publishers (owner approval handler) call `publish(order_id, event)` to push.

Restart-volatile by design: this is a 24h hackathon, not a queue system.
For production, swap the dict for Redis Streams or NATS.
"""
from __future__ import annotations
import asyncio
from typing import Any

_subscribers: dict[str, list[asyncio.Queue]] = {}


async def subscribe(order_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(order_id, []).append(q)
    return q


def unsubscribe(order_id: str, q: asyncio.Queue) -> None:
    qs = _subscribers.get(order_id)
    if not qs:
        return
    try:
        qs.remove(q)
    except ValueError:
        pass
    if not qs:
        _subscribers.pop(order_id, None)


async def publish(order_id: str, event: dict[str, Any]) -> None:
    for q in list(_subscribers.get(order_id, [])):
        await q.put(event)


def subscriber_count(order_id: str) -> int:
    return len(_subscribers.get(order_id, []))
