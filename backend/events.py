import asyncio
import json

_subscribers: set[asyncio.Queue] = set()


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue):
    _subscribers.discard(q)


async def broadcast(event_type: str, payload: dict):
    msg = json.dumps({"type": event_type, "data": payload})
    dead: set[asyncio.Queue] = set()
    for q in _subscribers:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.add(q)
    _subscribers.difference_update(dead)
