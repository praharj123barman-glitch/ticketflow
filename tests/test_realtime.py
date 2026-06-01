"""Real-time fan-out: a seat state change is pushed over Redis pub/sub to every
connected WebSocket client on that event (across what would be different workers)."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import User
from app.services import booking_service


def test_seat_change_is_pushed_to_all_connections(event_with_seats):
    event_id, seat_ids = event_with_seats

    # TestClient context runs the lifespan -> starts the pub/sub broker.
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws/events/{event_id}") as ws_a, \
             client.websocket_connect(f"/ws/events/{event_id}") as ws_b:
            # Each client first receives a full snapshot.
            assert ws_a.receive_json()["type"] == "snapshot"
            assert ws_b.receive_json()["type"] == "snapshot"
            time.sleep(0.4)  # let the broker finish psubscribe

            # A change happens elsewhere (another user holds a seat) -> publishes.
            db = SessionLocal()
            try:
                u = User(email="rt@test.dev", hashed_password="x")
                db.add(u)
                db.commit()
                booking_service.create_hold(db, u.id, event_id, [seat_ids[0]])
            finally:
                db.close()

            # BOTH live connections receive the delta.
            for ws in (ws_a, ws_b):
                msg = ws.receive_json()
                assert msg["type"] == "delta"
                changed = {s["id"]: s["status"] for s in msg["seats"]}
                assert changed.get(seat_ids[0]) == "HELD"


def test_seat_map_endpoint_served_from_cache_and_invalidates(client, auth_token, event_with_seats):
    event_id, seat_ids = event_with_seats
    from app.services import seatcache

    # First read builds + caches; version starts at baseline.
    first = client.get(f"/events/{event_id}/seats").json()
    assert any(s["id"] == seat_ids[0] and s["status"] == "AVAILABLE" for s in first)
    v0 = seatcache.current_version(event_id)

    # A hold changes a seat -> cache invalidated (version bumps) + reflected.
    db = SessionLocal()
    try:
        u = User(email="c@test.dev", hashed_password="x")
        db.add(u)
        db.commit()
        booking_service.create_hold(db, u.id, event_id, [seat_ids[0]])
    finally:
        db.close()

    assert seatcache.current_version(event_id) > v0
    after = client.get(f"/events/{event_id}/seats").json()
    assert any(s["id"] == seat_ids[0] and s["status"] == "HELD" for s in after)
