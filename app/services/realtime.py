"""Real-time seat updates via Redis pub/sub.

Publishers (the booking service, running sync in a threadpool) PUBLISH seat
deltas to `seatchanges:{event}`. Each app worker runs an async broker that
psubscribes to `seatchanges:*` and fans deltas out to the WebSocket clients
connected to THAT worker. Because the transport is Redis pub/sub, a change made
on any worker reaches clients on every worker — no sticky sessions required for
correctness (see docs/HLD.md).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading

from fastapi import WebSocket

from ..redis_client import redis_client as r
from . import seatcache

logger = logging.getLogger("ticketflow.realtime")

_CHANNEL = "seatchanges:{}"


def notify_seat_changes(event_id: int, deltas: list[dict]) -> None:
    """Invalidate the seat-map cache and publish the deltas. Best-effort: a
    pub/sub hiccup must never break a booking (the DB is the source of truth)."""
    try:
        seatcache.invalidate(event_id)
    except Exception:
        logger.exception("seatcache invalidate failed for event %s", event_id)
    try:
        r.publish(_CHANNEL.format(event_id), json.dumps({"event_id": event_id, "seats": deltas}))
    except Exception:
        logger.exception("seat-change publish failed for event %s", event_id)


class ConnectionManager:
    """Per-worker registry of WebSocket clients grouped by event."""

    def __init__(self) -> None:
        self.rooms: dict[int, set[WebSocket]] = {}

    async def connect(self, event_id: int, ws: WebSocket) -> None:
        await ws.accept()
        self.rooms.setdefault(event_id, set()).add(ws)

    def disconnect(self, event_id: int, ws: WebSocket) -> None:
        self.rooms.get(event_id, set()).discard(ws)

    async def broadcast(self, event_id: int, message: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self.rooms.get(event_id, ())):
            try:
                await ws.send_json(message)
            except Exception:
                logger.exception("broadcast send failed for event %s", event_id)
                dead.append(ws)
        for ws in dead:
            self.disconnect(event_id, ws)


manager = ConnectionManager()


def _run_broker(loop: asyncio.AbstractEventLoop) -> None:
    """Subscribe (synchronously, on a dedicated thread) to all seat-change
    channels and bridge each delta onto the app's event loop to fan out to the
    locally-connected WebSocket clients.

    Why a thread + sync client instead of redis.asyncio: the async pub/sub reader
    does not reliably surface messages under uvicorn's Windows ProactorEventLoop.
    The sync client is rock-solid; we hop back to the loop via
    run_coroutine_threadsafe to do the (async) WebSocket sends.
    """
    pubsub = r.pubsub()
    pubsub.psubscribe("seatchanges:*")
    logger.info("seat broker subscribed")
    while True:
        try:
            # Poll with a timeout: returns None on idle (no crash). Using
            # listen() here would propagate the connection's socket-read timeout
            # and kill the thread during quiet periods.
            msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        except Exception:
            logger.exception("seat broker read error; resubscribing")
            try:
                pubsub.close()
            except Exception:
                pass
            pubsub = r.pubsub()
            pubsub.psubscribe("seatchanges:*")
            continue

        if not msg or msg.get("type") != "pmessage":
            continue
        try:
            data = json.loads(msg["data"])
            ev = int(data["event_id"])
            asyncio.run_coroutine_threadsafe(
                manager.broadcast(ev, {"type": "delta", "seats": data["seats"]}), loop
            ).result(timeout=5)
        except Exception:
            logger.exception("seat broker dispatch failed")


def start_seat_broker(loop: asyncio.AbstractEventLoop) -> threading.Thread:
    """Launch the broker on a daemon thread bound to the given event loop."""
    t = threading.Thread(target=_run_broker, args=(loop,), name="seat-broker", daemon=True)
    t.start()
    return t
