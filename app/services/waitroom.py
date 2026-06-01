"""Virtual waiting room (the Ticketmaster on-sale pattern).

Per event, two Redis structures:
  * QUEUE  (sorted set)  member=session token, score=join time (ms) -> FIFO fairness.
  * ACTIVE (sorted set)  member=session token, score=expiry (ms)    -> who's let in.

Arrivals are admitted immediately while ACTIVE < threshold; otherwise they wait in
the QUEUE. A background admitter promotes the front of the QUEUE into ACTIVE at a
fixed rate, shedding the thundering herd away from the hold/booking endpoints.

Admission tokens are REQUIRED by the hold/checkout endpoints (when enabled), so
over-threshold users physically cannot reach the booking path.
"""
from __future__ import annotations

import math
import time
import uuid

from ..config import settings
from ..redis_client import redis_client as r


class WaitroomError(Exception):
    """Raised when a request lacks a valid admission token (caller -> 403)."""


def _now_ms() -> int:
    return int(time.time() * 1000)


def _q(event_id: int) -> str:
    return f"waitroom:q:{event_id}"


def _active(event_id: int) -> str:
    return f"waitroom:active:{event_id}"


_EVENTS = "waitroom:events"  # set of event ids that currently have a queue


def _prune_active(event_id: int) -> None:
    """Drop admitted sessions whose TTL lapsed (no heartbeat)."""
    r.zremrangebyscore(_active(event_id), "-inf", _now_ms())


def _admit(event_id: int, token: str) -> None:
    r.zadd(_active(event_id), {token: _now_ms() + settings.waitroom_session_ttl_seconds * 1000})


def active_count(event_id: int) -> int:
    _prune_active(event_id)
    return r.zcard(_active(event_id))


def join(event_id: int, token: str | None = None) -> dict:
    """Join the waiting room. Admits immediately if there is capacity (or the
    room is disabled), else enqueues. Returns {token, status, position?, ...}."""
    token = token or uuid.uuid4().hex

    if not settings.waitroom_enabled:
        _admit(event_id, token)
        return {"token": token, "status": "admitted"}

    _prune_active(event_id)

    if r.zscore(_active(event_id), token) is not None:
        _admit(event_id, token)  # refresh
        return {"token": token, "status": "admitted"}

    rank = r.zrank(_q(event_id), token)
    if rank is not None:
        return _waiting_payload(event_id, token, rank)

    if r.zcard(_active(event_id)) < settings.waitroom_active_threshold:
        _admit(event_id, token)
        return {"token": token, "status": "admitted"}

    r.zadd(_q(event_id), {token: _now_ms()})
    r.sadd(_EVENTS, event_id)
    rank = r.zrank(_q(event_id), token)
    return _waiting_payload(event_id, token, rank if rank is not None else 0)


def status(event_id: int, token: str) -> dict:
    """Poll status. Heartbeats an admitted session so it stays active while the
    user is on the seat map."""
    if not settings.waitroom_enabled:
        return {"token": token, "status": "admitted"}

    _prune_active(event_id)
    if r.zscore(_active(event_id), token) is not None:
        _admit(event_id, token)  # heartbeat
        return {"token": token, "status": "admitted"}

    rank = r.zrank(_q(event_id), token)
    if rank is not None:
        return _waiting_payload(event_id, token, rank)

    return {"token": token, "status": "expired"}  # neither active nor queued -> rejoin


def is_admitted(event_id: int, token: str | None) -> bool:
    """Gate check used by hold/checkout. Heartbeats on success."""
    if not settings.waitroom_enabled:
        return True
    if not token:
        return False
    _prune_active(event_id)
    if r.zscore(_active(event_id), token) is None:
        return False
    _admit(event_id, token)  # heartbeat
    return True


def ensure_admitted(event_id: int, token: str | None) -> None:
    if not is_admitted(event_id, token):
        raise WaitroomError(event_id)


def admit_step() -> int:
    """One admitter tick: promote queued users into ACTIVE up to the threshold,
    for every event with a queue. Returns number admitted."""
    admitted = 0
    for raw in r.smembers(_EVENTS):
        event_id = int(raw)
        # Per-event lock so multiple admitter workers never over-admit.
        lock_key = f"waitroom:admitlock:{event_id}"
        if not r.set(lock_key, "1", nx=True, px=settings.waitroom_admit_interval_seconds * 1000):
            continue
        try:
            _prune_active(event_id)
            capacity = settings.waitroom_active_threshold - r.zcard(_active(event_id))
            if capacity <= 0:
                continue
            n = min(capacity, settings.waitroom_admit_batch)
            popped = r.zpopmin(_q(event_id), n)  # atomic FIFO pop
            for member, _score in popped:
                _admit(event_id, member)
                admitted += 1
            if r.zcard(_q(event_id)) == 0:
                r.srem(_EVENTS, event_id)
        finally:
            r.delete(lock_key)
    return admitted


def _waiting_payload(event_id: int, token: str, rank: int) -> dict:
    position = rank + 1
    batch = max(1, settings.waitroom_admit_batch)
    eta = math.ceil(position / batch) * settings.waitroom_admit_interval_seconds
    return {
        "token": token,
        "status": "waiting",
        "position": position,
        "ahead": rank,
        "estimated_wait_seconds": eta,
    }
