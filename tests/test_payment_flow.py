"""Edge cases for the hold -> pay -> confirm lifecycle:
  * hold expires mid-checkout  -> 410, seats released, nothing charged
  * confirm after expiry       -> REFUND_REQUIRED, no booking, no seats granted
  * duplicate webhook delivery -> exactly one booking
  * double-submit confirm      -> exactly one booking
  * DB partial-unique index    -> final guard against double-selling a seat
"""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import (
    Booking,
    BookingItem,
    BookingStatus,
    Event,
    Hold,
    HoldStatus,
    Seat,
    SeatStatus,
    User,
)
from app.services import booking_service


def _event_seat(db, n: int = 1) -> tuple[int, list[int]]:
    event = Event(name="E", starts_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))
    db.add(event)
    db.flush()
    seats = [Seat(event_id=event.id, seat_number=f"A{i}", price_cents=1000,
                  status=SeatStatus.AVAILABLE) for i in range(n)]
    db.add_all(seats)
    db.commit()
    return event.id, [s.id for s in seats]


def _user(db, email="u@test.dev") -> int:
    u = User(email=email, hashed_password="x", full_name="U")
    db.add(u)
    db.commit()
    return u.id


def _force_expire(db, hold_id: int) -> None:
    """Backdate the hold's TTL to simulate it lapsing mid-checkout."""
    hold = db.get(Hold, hold_id)
    hold.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
    db.commit()


# ---- checkout after expiry ----
def test_checkout_on_expired_hold_returns_410_and_releases(client, auth_token, event_with_seats):
    event_id, seat_ids = event_with_seats
    h = {"Authorization": f"Bearer {auth_token}"}
    hold = client.post("/holds", json={"event_id": event_id, "seat_ids": [seat_ids[0]]}, headers=h).json()

    db = SessionLocal()
    try:
        _force_expire(db, hold["id"])
    finally:
        db.close()

    co = client.post(f"/holds/{hold['id']}/checkout", headers=h)
    assert co.status_code == 410  # no Stripe session created -> nothing charged

    seats = client.get(f"/events/{event_id}/seats").json()
    assert [s for s in seats if s["id"] == seat_ids[0]][0]["status"] == "AVAILABLE"


# ---- confirm after expiry must refund, not grant ----
def test_confirm_after_expiry_requires_refund_no_booking(db):
    event_id, seat_ids = _event_seat(db)
    user_id = _user(db)
    hold = booking_service.create_hold(db, user_id, event_id, seat_ids)
    _force_expire(db, hold.id)

    result = booking_service.confirm_hold(db, hold.id, payment_reference="pi_x", stripe_event_id="evt_exp")
    assert result.outcome == booking_service.REFUND_REQUIRED
    assert result.booking is None

    db.expire_all()
    assert db.query(Booking).count() == 0
    assert db.get(Seat, seat_ids[0]).status == SeatStatus.AVAILABLE
    assert db.get(Hold, hold.id).status == HoldStatus.EXPIRED


# ---- duplicate webhook delivery ----
def test_duplicate_webhook_creates_one_booking(client, auth_token, event_with_seats):
    event_id, seat_ids = event_with_seats
    h = {"Authorization": f"Bearer {auth_token}"}
    hold = client.post("/holds", json={"event_id": event_id, "seat_ids": [seat_ids[0]]}, headers=h).json()
    event = {
        "id": "evt_dupe_1",
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"hold_id": str(hold["id"])}, "payment_intent": "pi_1"}},
    }
    r1 = client.post("/webhooks/stripe", json=event)
    r2 = client.post("/webhooks/stripe", json=event)  # exact duplicate delivery
    assert r1.json()["status"] == "confirmed"
    assert r2.json()["status"] == "already_done"

    db = SessionLocal()
    try:
        assert db.query(Booking).filter(Booking.hold_id == hold["id"]).count() == 1
    finally:
        db.close()


# ---- double-submit confirm (concurrent) ----
def test_double_submit_confirm_one_booking(db):
    event_id, seat_ids = _event_seat(db)
    user_id = _user(db)
    hold = booking_service.create_hold(db, user_id, event_id, seat_ids)

    def confirm() -> str:
        session = SessionLocal()
        try:
            return booking_service.confirm_hold(session, hold.id, payment_reference="pi_y").outcome
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [f.result() for f in as_completed([pool.submit(confirm), pool.submit(confirm)])]

    assert outcomes.count(booking_service.CONFIRMED) == 1
    assert outcomes.count(booking_service.ALREADY_DONE) == 1

    db.expire_all()
    assert db.query(Booking).filter(Booking.hold_id == hold.id).count() == 1
    assert db.get(Seat, seat_ids[0]).status == SeatStatus.SOLD


# ---- checkout return URLs derive from the public origin ----
def test_checkout_urls_derive_from_public_base_url(monkeypatch):
    from app.config import settings
    from app.services import payment_service

    monkeypatch.setattr(settings, "public_base_url", "https://tickets.example.com")
    success, cancel = payment_service._return_urls(42)
    assert success.startswith("https://tickets.example.com/booking/success?hold=42")
    assert "{CHECKOUT_SESSION_ID}" in success           # Stripe substitutes this
    assert cancel == "https://tickets.example.com/booking/cancel?hold=42"


# ---- dev-confirm endpoint (offline pay -> confirm beat) ----
def test_dev_confirm_creates_confirmed_booking_with_tickets(client, auth_token, event_with_seats):
    event_id, seat_ids = event_with_seats
    h = {"Authorization": f"Bearer {auth_token}"}
    hold = client.post("/holds", json={"event_id": event_id, "seat_ids": [seat_ids[0], seat_ids[1]]}, headers=h).json()

    r = client.post(f"/holds/{hold['id']}/dev-confirm", headers=h)
    assert r.status_code == 200
    booking = r.json()
    assert booking["status"] == "CONFIRMED"
    assert booking["hold_id"] == hold["id"]
    assert len(booking["tickets"]) == 2  # one e-ticket per seat

    # idempotent: a second call returns the same booking, not a duplicate
    r2 = client.post(f"/holds/{hold['id']}/dev-confirm", headers=h)
    assert r2.status_code == 200 and r2.json()["id"] == booking["id"]

    # the QR renders as a scalable <path> (not blank namespaced rects)
    qr = client.get(f"/tickets/{booking['tickets'][0]['code']}/qr.svg", headers=h)
    assert qr.status_code == 200 and b"<path" in qr.content and b"viewBox" in qr.content


def test_dev_confirm_rejects_other_users_hold(client, auth_token, event_with_seats):
    event_id, seat_ids = event_with_seats
    owner = {"Authorization": f"Bearer {auth_token}"}
    hold = client.post("/holds", json={"event_id": event_id, "seat_ids": [seat_ids[0]]}, headers=owner).json()

    # a different user must not be able to confirm someone else's hold
    client.post("/auth/register", json={"email": "intruder@test.dev", "password": "password123"})
    other = client.post("/auth/login", data={"username": "intruder@test.dev", "password": "password123"}).json()
    r = client.post(f"/holds/{hold['id']}/dev-confirm", headers={"Authorization": f"Bearer {other['access_token']}"})
    assert r.status_code == 404


# ---- DB-level final guard ----
def test_partial_unique_index_blocks_double_sell(db):
    event_id, seat_ids = _event_seat(db)
    user_id = _user(db)
    hold = booking_service.create_hold(db, user_id, event_id, seat_ids)
    booking_service.confirm_hold(db, hold.id, payment_reference="pi_z")

    # Manually attempt to record a SECOND active sale of the same seat — the
    # partial unique index (seat_id WHERE active) must reject it.
    rogue = Booking(user_id=user_id, event_id=event_id, status=BookingStatus.CONFIRMED, total_cents=1000)
    db.add(rogue)
    db.flush()
    db.add(BookingItem(booking_id=rogue.id, seat_id=seat_ids[0], price_cents=1000, active=True))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
