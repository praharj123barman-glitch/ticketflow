"""Fixed-window rate limiter backed by Redis.

Each client (keyed by IP) gets a budget of N requests per 60s window. The first
request in a window sets a TTL so the counter self-expires. This is the simple,
battle-tested fixed-window algorithm — good enough to demonstrate the concept
and protect the booking endpoints from abusive bursts.

Trade-off (documented in LLD): fixed windows allow a 2x burst at the window
boundary. A sliding-window or token-bucket would smooth that out; noted as the
production upgrade path.
"""
from __future__ import annotations

import time

from fastapi import HTTPException, Request, status

from ..config import settings
from ..redis_client import redis_client


def rate_limiter(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    window = int(time.time() // 60)
    key = f"rl:{client_ip}:{window}"

    count = redis_client.incr(key)
    if count == 1:
        redis_client.expire(key, 60)

    if count > settings.rate_limit_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again shortly.",
            headers={"Retry-After": "60"},
        )
