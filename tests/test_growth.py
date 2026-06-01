"""User-growth surface: guest checkout, the funnel view beacon, and the
viewed -> held -> paid numbers that surface on the organizer dashboard."""
from __future__ import annotations

from sqlalchemy import select

from app.models import Event, User


def _organizer(client, db, event_id: int) -> str:
    """Register an organizer, make them own the event, return their token."""
    client.post("/auth/register", json={"email": "org@test.dev", "password": "password123", "role": "ORGANIZER"})
    tok = client.post("/auth/login", data={"username": "org@test.dev", "password": "password123"}).json()["access_token"]
    org = db.execute(select(User).where(User.email == "org@test.dev")).scalar_one()
    db.get(Event, event_id).organizer_id = org.id
    db.commit()
    return tok


def test_guest_can_book_without_signup(client, event_with_seats):
    event_id, seat_ids = event_with_seats
    # no register/login — just a guest token
    gt = client.post("/auth/guest").json()["access_token"]
    h = {"Authorization": f"Bearer {gt}"}

    hold = client.post("/holds", json={"event_id": event_id, "seat_ids": [seat_ids[0]]}, headers=h)
    assert hold.status_code == 201
    booking = client.post(f"/holds/{hold.json()['id']}/dev-confirm", headers=h)
    assert booking.status_code == 200 and booking.json()["status"] == "CONFIRMED"


def test_view_beacon_dedupes_per_session(client, event_with_seats, db):
    event_id, _ = event_with_seats
    # same session fires twice (refresh/poll) -> counts once; a new session -> +1
    for tok in ["sess-aaaaaaaa", "sess-aaaaaaaa", "sess-bbbbbbbb"]:
        assert client.post(f"/events/{event_id}/view", json={"session_token": tok}).status_code == 204

    org = _organizer(client, db, event_id)
    stats = client.get(f"/organizer/events/{event_id}/stats", headers={"Authorization": f"Bearer {org}"}).json()
    assert stats["funnel"]["views"] == 2


def test_funnel_counts_views_holds_paid(client, event_with_seats, db):
    event_id, seat_ids = event_with_seats
    client.post(f"/events/{event_id}/view", json={"session_token": "visitor-1"})
    client.post(f"/events/{event_id}/view", json={"session_token": "visitor-2"})

    gt = client.post("/auth/guest").json()["access_token"]
    h = {"Authorization": f"Bearer {gt}"}
    hold = client.post("/holds", json={"event_id": event_id, "seat_ids": [seat_ids[0]]}, headers=h).json()
    client.post(f"/holds/{hold['id']}/dev-confirm", headers=h)

    org = _organizer(client, db, event_id)
    f = client.get(f"/organizer/events/{event_id}/stats", headers={"Authorization": f"Bearer {org}"}).json()["funnel"]
    assert f["views"] == 2 and f["holds"] == 1 and f["paid"] == 1
    assert f["view_to_hold"] == 50.0 and f["hold_to_paid"] == 100.0 and f["view_to_paid"] == 50.0
