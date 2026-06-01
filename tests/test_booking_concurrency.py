"""Headline concurrency test: the two-layer lock still guarantees that
concurrent requests cannot reserve the same seat twice — the contention point is
now the HOLD (reservation), which is exactly where the race must be resolved.

50 threads race for one seat -> exactly ONE hold, 49 rejected, 0 double-holds.
"""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.database import SessionLocal
from app.models import Event, Hold, HoldStatus, Seat, SeatStatus, User
from app.services import booking_service
from app.services.booking_service import SeatUnavailableError
from app.services.lock import LockAcquisitionError

# Both are legitimate "did not get the seat" outcomes under contention.
CONTENTION_REJECTIONS = (SeatUnavailableError, LockAcquisitionError)


def _make_users(db, n: int) -> list[int]:
    users = [User(email=f"c{i}@test.dev", hashed_password="x", full_name=f"C{i}") for i in range(n)]
    db.add_all(users)
    db.commit()
    return [u.id for u in users]


def _single_seat_event(db) -> tuple[int, int]:
    event = Event(name="Hot Show",
                  starts_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))
    db.add(event)
    db.flush()
    seat = Seat(event_id=event.id, seat_number="A1", price_cents=1000, status=SeatStatus.AVAILABLE)
    db.add(seat)
    db.commit()
    return event.id, seat.id


def test_concurrent_holds_single_seat_yield_exactly_one_winner(db):
    N = 50
    event_id, seat_id = _single_seat_event(db)
    user_ids = _make_users(db, N)

    def attempt(user_id: int) -> str:
        session = SessionLocal()
        try:
            booking_service.create_hold(session, user_id, event_id, [seat_id])
            return "held"
        except CONTENTION_REJECTIONS:
            return "rejected"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=N) as pool:
        results = [f.result() for f in as_completed([pool.submit(attempt, uid) for uid in user_ids])]

    assert results.count("held") == 1, f"expected exactly 1 winner, got {results.count('held')}"
    assert results.count("rejected") == N - 1

    db.expire_all()
    seat = db.get(Seat, seat_id)
    assert seat.status == SeatStatus.HELD
    assert db.query(Hold).filter(Hold.status == HoldStatus.ACTIVE).count() == 1


def test_concurrent_holds_distinct_seats_all_succeed(db):
    N = 20
    event = Event(name="Wide Show",
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
            booking_service.create_hold(session, user_id, event.id, [seat_id])
            return "held"
        except CONTENTION_REJECTIONS:
            return "rejected"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=N) as pool:
        futures = [pool.submit(attempt, user_ids[i], seat_ids[i]) for i in range(N)]
        results = [f.result() for f in as_completed(futures)]

    assert results.count("held") == N
