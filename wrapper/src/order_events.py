"""In-memory order status store + pub/sub.

Two read paths:
  - publish/subscribe (asyncio.Queue) for live SSE/WebSocket consumers.
  - get_state for short-polling consumers (the website chat widget).

Cloudflare's quick tunnels buffer SSE; the website widget polls instead.
Restart-volatile by design: 24h hackathon, not a queue system.
"""
from __future__ import annotations
import asyncio
from typing import Any

_subscribers: dict[str, list[asyncio.Queue]] = {}
_latest: dict[str, dict[str, Any]] = {}
_history: dict[str, list[dict[str, Any]]] = {}


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
    _latest[order_id] = event
    _history.setdefault(order_id, []).append(event)
    for q in list(_subscribers.get(order_id, [])):
        await q.put(event)


def get_state(order_id: str) -> dict[str, Any] | None:
    """Latest known event for this order, or None."""
    return _latest.get(order_id)


def get_history(order_id: str) -> list[dict[str, Any]]:
    """Full event history (in publish order) for this order."""
    return list(_history.get(order_id, []))


def subscriber_count(order_id: str) -> int:
    return len(_subscribers.get(order_id, []))
