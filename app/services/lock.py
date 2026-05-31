"""Redis-based distributed lock — the FIRST layer of double-booking defence.

Why a distributed lock when we also lock rows in Postgres?
  * The DB row lock (SELECT ... FOR UPDATE) is the correctness guarantee, but it
    only kicks in once a transaction reaches the database. Under a thundering
    herd (thousands of users hammering the same popular seat), letting every
    request open a transaction and queue on the row lock wastes DB connections.
  * The Redis lock lets us reject/serialise contention cheaply *before* touching
    the database, protecting the connection pool. It works across every gunicorn
    worker and every app instance, which an in-process lock cannot.

Correctness details:
  * Lock value is a random token. Release is done with a Lua script that checks
    the token before deleting, so a worker can never delete a lock that a *later*
    worker acquired after this one's TTL expired (the classic lock-stealing bug).
  * Every lock has a TTL (lock_ttl_ms) so a crashed worker can never deadlock the
    system permanently.
  * Multiple keys are always acquired in sorted order by the caller, which makes
    a deadlock between two multi-seat bookings impossible (ordered locking).
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from ..config import settings
from ..redis_client import redis_client

# Atomically delete the key only if we still own it (value == our token).
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


class LockAcquisitionError(Exception):
    """Raised when a lock could not be acquired within the timeout."""


@contextmanager
def multi_lock(keys: Sequence[str]) -> Iterator[None]:
    """Acquire all `keys` (caller must pass them in a stable, sorted order),
    yield, then release exactly the locks we own."""
    token = str(uuid.uuid4())
    acquired: list[str] = []
    deadline = time.monotonic() + settings.lock_acquire_timeout_ms / 1000.0

    try:
        for key in keys:
            if not _acquire_one(key, token, deadline):
                raise LockAcquisitionError(f"timed out acquiring lock {key}")
            acquired.append(key)
        yield
    finally:
        for key in acquired:
            try:
                redis_client.eval(_RELEASE_SCRIPT, 1, key, token)
            except Exception:
                # Best-effort release; the TTL guarantees eventual cleanup.
                pass


def _acquire_one(key: str, token: str, deadline: float) -> bool:
    delay = 0.01
    while True:
        # SET key token NX PX ttl  — atomic "acquire if absent with expiry"
        if redis_client.set(key, token, nx=True, px=settings.lock_ttl_ms):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(delay)
        delay = min(delay * 1.6, 0.1)  # capped exponential backoff
