"""THE headline test: prove that concurrent requests cannot double-book a seat.

We fire N threads at the SAME single seat through the real booking service
(each thread with its own DB session, exactly like separate worker processes
would have). Correctness requires exactly ONE success; everyone else must get a
SeatUnavailableError.

This is the test whose result becomes a resume bullet:
    "verified under concurrent load — 50 parallel requests on 1 seat -> 1 booking,
     49 rejected, 0 double-bookings."
"""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.database import SessionLocal
from app.models import Booking, Event, Seat, SeatStatus, User
from app.services import booking_service
from app.services.booking_service import SeatUnavailableError
from app.services.lock import LockAcquisitionError

# Both are legitimate "did not get the seat" outcomes under contention: the seat
# was already taken (409) OR we couldn't grab the lock in time (503 retry). Either
# way it is NOT a successful booking — which is exactly what we assert.
CONTENTION_REJECTIONS = (SeatUnavailableError, LockAcquisitionError)


def _make_users(db, n: int) -> list[int]:
    users = [User(email=f"c{i}@test.dev", hashed_password="x", full_name=f"C{i}") for i in range(n)]
    db.add_all(users)
    db.commit()
    return [u.id for u in users]


def _make_single_seat_event(db) -> tuple[int, int]:
    event = Event(name="Hot Show", venue="Arena",
                  starts_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))
    db.add(event)
    db.flush()
    seat = Seat(event_id=event.id, seat_number="A1", price_cents=1000, status=SeatStatus.AVAILABLE)
    db.add(seat)
    db.commit()
    return event.id, seat.id


def test_concurrent_booking_single_seat_yields_exactly_one_winner(db):
    N = 50
    event_id, seat_id = _make_single_seat_event(db)
    user_ids = _make_users(db, N)

    def attempt(user_id: int) -> str:
        # Each thread gets its OWN session — mirrors independent workers.
        session = SessionLocal()
        try:
            booking_service.confirm_booking(session, user_id, event_id, [seat_id])
            return "success"
        except CONTENTION_REJECTIONS:
            return "rejected"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=N) as pool:
        results = [f.result() for f in as_completed([pool.submit(attempt, uid) for uid in user_ids])]

    successes = results.count("success")
    rejected = results.count("rejected")

    assert successes == 1, f"expected exactly 1 winner, got {successes}"
    assert rejected == N - 1

    # Source-of-truth check: the seat is BOOKED and exactly one booking row exists.
    db.expire_all()
    seat = db.get(Seat, seat_id)
    assert seat.status == SeatStatus.BOOKED
    assert db.query(Booking).count() == 1


def test_concurrent_booking_distinct_seats_all_succeed(db):
    """Sanity check that the locking does not serialise *independent* seats:
    N users each booking a different seat should all succeed."""
    N = 20
    event = Event(name="Wide Show", venue="Hall",
                  starts_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))
    db.add(event)
    db.flush()
    seats = [Seat(event_id=event.id, seat_number=f"A{i}", price_cents=1000,
                  status=SeatStatus.AVAILABLE) for i in range(N)]
    db.add_all(seats)
    db.commit()
    seat_ids = [s.id for s in seats]
    user_ids = _make_users(db, N)

    def attempt(user_id: int, seat_id: int) -> str:
        session = SessionLocal()
        try:
            booking_service.confirm_booking(session, user_id, event.id, [seat_id])
            return "success"
        except CONTENTION_REJECTIONS:
            return "rejected"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=N) as pool:
        futures = [pool.submit(attempt, user_ids[i], seat_ids[i]) for i in range(N)]
        results = [f.result() for f in as_completed(futures)]

    assert results.count("success") == N
