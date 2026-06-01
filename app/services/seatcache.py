"""Seat-map Redis cache with version-based invalidation.

The seat map (layout + live availability) is the hottest read on the system. We
serve it from a Redis cache and bump a per-event version key on ANY seat change,
so the cached payload self-invalidates without us having to enumerate what
changed. Cache misses (and version mismatches) rebuild from Postgres and re-cache.

Keys per event:
  * seatmap:ver:{event}  -> integer, INCR on any seat state change.
  * seatmap:{event}      -> JSON {"v": <version>, "seats": [...]}, short TTL.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Seat
from ..redis_client import redis_client as r

_CACHE_TTL_SECONDS = 300


def _ver_key(event_id: int) -> str:
    return f"seatmap:ver:{event_id}"


def _map_key(event_id: int) -> str:
    return f"seatmap:{event_id}"


def current_version(event_id: int) -> int:
    v = r.get(_ver_key(event_id))
    return int(v) if v is not None else 0


def invalidate(event_id: int) -> int:
    """Bump the version (self-invalidates the cached payload) and drop the blob."""
    v = r.incr(_ver_key(event_id))
    r.delete(_map_key(event_id))
    return v


def _serialize(seats: list[Seat]) -> list[dict]:
    return [
        {"id": s.id, "section": s.section, "seat_number": s.seat_number,
         "price_cents": s.price_cents, "status": s.status, "version": s.version}
        for s in seats
    ]


def get_seat_map(db: Session, event_id: int) -> list[dict]:
    """Return the seat map from cache when the cached version matches the current
    version key; otherwise rebuild from Postgres and re-cache. The hot path is a
    single Redis GET + a version GET — Postgres is only touched on miss."""
    cur = current_version(event_id)
    cached = r.get(_map_key(event_id))
    if cached:
        payload = json.loads(cached)
        if payload.get("v") == cur:
            return payload["seats"]

    seats = db.execute(
        select(Seat).where(Seat.event_id == event_id).order_by(Seat.id)
    ).scalars().all()
    data = _serialize(seats)
    r.set(_map_key(event_id), json.dumps({"v": cur, "seats": data}), ex=_CACHE_TTL_SECONDS)
    return data
