"""WebSocket channel for live seat updates (one channel per event).

On connect, the client gets a full snapshot from the seat-map cache, then a
stream of {type: "delta", seats: [...]} messages as seats change. Read-only: the
server ignores anything the client sends (kept open as a keepalive)."""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from ..database import SessionLocal
from ..services import realtime, seatcache

router = APIRouter()


@router.websocket("/ws/events/{event_id}")
async def seat_stream(ws: WebSocket, event_id: int) -> None:
    await realtime.manager.connect(event_id, ws)
    try:
        db = SessionLocal()
        try:
            seats = await run_in_threadpool(seatcache.get_seat_map, db, event_id)
        finally:
            db.close()
        await ws.send_json({"type": "snapshot", "seats": seats})

        while True:
            await ws.receive_text()  # ignore; keeps the socket open
    except WebSocketDisconnect:
        pass
    finally:
        realtime.manager.disconnect(event_id, ws)
