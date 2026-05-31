"""Booking domain logic — the SECOND (authoritative) layer of concurrency control.

This module is the centrepiece of TicketFlow. Every state change to a seat goes
through here, inside a transaction that holds a pessimistic row lock. Combined
with the Redis lock in lock.py, two concurrent requests for the same seat can
never both succeed.

The flow for a confirmed booking:
    1. Sort seat ids -> derive lock keys -> acquire Redis locks (ordered).
    2. BEGIN; SELECT ... FOR UPDATE on those seat rows (DB row lock).
    3. Re-validate availability *inside* the lock (never trust a pre-check).
    4. Flip seats to BOOKED, write the Booking + items, COMMIT.
    5. Release Redis locks (in the context manager's finally).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Booking, BookingItem, BookingStatus, Seat, SeatStatus
from .lock import multi_lock


class SeatUnavailableError(Exception):
    def __init__(self, seat_ids: list[int]):
        self.seat_ids = seat_ids
        super().__init__(f"seats unavailable: {seat_ids}")


class SeatNotFoundError(Exception):
    def __init__(self, seat_ids: list[int]):
        self.seat_ids = seat_ids
        super().__init__(f"seats not found: {seat_ids}")


class TooManySeatsError(Exception):
    pass


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _lock_keys(seat_ids: list[int]) -> list[str]:
    # Sorted so any two bookings touching overlapping seats grab locks in the
    # same order -> no circular wait -> no deadlock.
    return [f"lock:seat:{sid}" for sid in sorted(set(seat_ids))]


def _hold_active(seat: Seat, now: dt.datetime) -> bool:
    return (
        seat.status == SeatStatus.HELD
        and seat.hold_expires_at is not None
        and seat.hold_expires_at > now
    )


def _bookable_by(seat: Seat, user_id: int, now: dt.datetime) -> bool:
    """A seat is bookable by this user if it is AVAILABLE, or if its only hold is
    an expired one, or if it is currently held by *this same* user."""
    if seat.status == SeatStatus.AVAILABLE:
        return True
    if seat.status == SeatStatus.HELD:
        if not _hold_active(seat, now):
            return True  # stale hold -> treat as available (lazy expiry)
        return seat.held_by == user_id
    return False  # BOOKED


def hold_seats(db: Session, user_id: int, event_id: int, seat_ids: list[int]):
    """Temporarily reserve seats for `user_id` for seat_hold_seconds."""
    seat_ids = sorted(set(seat_ids))
    if len(seat_ids) > settings.max_seats_per_booking:
        raise TooManySeatsError()

    now = _utcnow()
    expires = now + dt.timedelta(seconds=settings.seat_hold_seconds)

    with multi_lock(_lock_keys(seat_ids)):
        seats = _select_for_update(db, event_id, seat_ids)
        _ensure_all_exist(seats, seat_ids)

        unavailable = [s.id for s in seats if not _bookable_by(s, user_id, now)]
        if unavailable:
            db.rollback()
            raise SeatUnavailableError(unavailable)

        for s in seats:
            s.status = SeatStatus.HELD
            s.held_by = user_id
            s.hold_expires_at = expires
            s.version += 1
        db.commit()

    return expires


def confirm_booking(db: Session, user_id: int, event_id: int, seat_ids: list[int]) -> Booking:
    """Confirm a booking for the given seats. This is the write path that the
    concurrency test hammers."""
    seat_ids = sorted(set(seat_ids))
    if len(seat_ids) > settings.max_seats_per_booking:
        raise TooManySeatsError()

    now = _utcnow()

    with multi_lock(_lock_keys(seat_ids)):
        seats = _select_for_update(db, event_id, seat_ids)
        _ensure_all_exist(seats, seat_ids)

        unavailable = [s.id for s in seats if not _bookable_by(s, user_id, now)]
        if unavailable:
            db.rollback()
            raise SeatUnavailableError(unavailable)

        booking = Booking(
            user_id=user_id,
            event_id=event_id,
            status=BookingStatus.CONFIRMED,
            total_cents=sum(s.price_cents for s in seats),
        )
        db.add(booking)
        db.flush()  # assign booking.id without ending the transaction

        for s in seats:
            s.status = SeatStatus.BOOKED
            s.held_by = None
            s.hold_expires_at = None
            s.version += 1
            db.add(BookingItem(booking_id=booking.id, seat_id=s.id, price_cents=s.price_cents))

        db.commit()
        db.refresh(booking)
        return booking


def cancel_booking(db: Session, user_id: int, booking_id: int) -> Booking:
    booking = db.get(Booking, booking_id)
    if booking is None or booking.user_id != user_id:
        raise SeatNotFoundError([])
    if booking.status == BookingStatus.CANCELLED:
        return booking

    seat_ids = [item.seat_id for item in booking.items]
    with multi_lock(_lock_keys(seat_ids)):
        seats = _select_for_update(db, booking.event_id, seat_ids)
        for s in seats:
            s.status = SeatStatus.AVAILABLE
            s.held_by = None
            s.hold_expires_at = None
            s.version += 1
        booking.status = BookingStatus.CANCELLED
        db.commit()
        db.refresh(booking)
    return booking


def release_expired_holds(db: Session) -> int:
    """Sweep stale HELD seats back to AVAILABLE. Called periodically by the
    background sweeper; lazy expiry in _bookable_by already covers correctness,
    this just keeps the seat map tidy for reads."""
    now = _utcnow()
    seats = db.execute(
        select(Seat).where(Seat.status == SeatStatus.HELD, Seat.hold_expires_at < now)
    ).scalars().all()
    for s in seats:
        s.status = SeatStatus.AVAILABLE
        s.held_by = None
        s.hold_expires_at = None
        s.version += 1
    db.commit()
    return len(seats)


# --- internals ---
def _select_for_update(db: Session, event_id: int, seat_ids: list[int]) -> list[Seat]:
    """Row-level pessimistic lock. Any other transaction touching these rows
    blocks here until we commit/rollback."""
    return list(
        db.execute(
            select(Seat)
            .where(Seat.id.in_(seat_ids), Seat.event_id == event_id)
            .with_for_update()
            .order_by(Seat.id)  # deterministic lock order at the DB layer too
        ).scalars().all()
    )


def _ensure_all_exist(seats: list[Seat], seat_ids: list[int]) -> None:
    found = {s.id for s in seats}
    missing = [sid for sid in seat_ids if sid not in found]
    if missing:
        raise SeatNotFoundError(missing)
