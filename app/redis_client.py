"""Shared Redis connection.

Redis serves three roles in TicketFlow:
  1. Distributed locking (first line of defence against double-booking).
  2. Rate limiting (fixed-window counters per client).
  3. (Extension point) caching of hot read paths like the seat map.
"""
import redis

from .config import settings

# protocol=2 (RESP2) keeps us compatible with any Redis >= 2.x. Our command set
# (SET/GET/INCR/EXPIRE/EVAL/PING) needs nothing from RESP3, so we avoid the RESP3
# HELLO handshake that newer clients send by default.
redis_client = redis.from_url(settings.redis_url, decode_responses=True, protocol=2)
