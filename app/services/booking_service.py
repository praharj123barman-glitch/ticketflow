"""Booking domain logic — the authoritative concurrency layer.

The lifecycle is now: select -> HOLD -> pay -> CONFIRM.

  * create_hold:    reserves seats (AVAILABLE -> HELD) all-or-nothing, behind the
                    same two-layer lock (Redis distributed lock + Postgres
                    SELECT ... FOR UPDATE). Creates a Hold (ACTIVE, TTL).
  * confirm_hold:   called after payment succeeds (Stripe webhook). Converts a
                    still-valid hold into a Booking (HELD -> SOLD) in one
                    transaction. Fully idempotent: duplicate webhooks / double
                    submits never create two bookings or grant seats twice.
  * release_expired_holds: sweeper that reconciles Postgres for holds whose TTL
                    lapsed (the Redis lock TTL only protects the critical
                    section; the DB row state must be swept back to AVAILABLE).

Deadlock-freedom: every path acquires the Redis seat locks in sorted order, then
takes Postgres row locks in a fixed order — SEATS first, then HOLDS — so no two
paths can form a circular wait.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Booking,
    BookingItem,
    BookingStatus,
    Event,
    Hold,
    HoldItem,
    HoldStatus,
    ProcessedWebhookEvent,
    Seat,
    SeatStatus,
    User,
)
from . import email_service, ticket_service
from .lock import multi_lock
from .realtime import notify_seat_changes


def _deltas(seats: list[Seat]) -> list[dict]:
    """Build the change payload BEFORE commit (attributes are still populated)."""
    return [{"id": s.id, "status": s.status, "version": s.version} for s in seats]


# ---- errors ----
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


class HoldNotFoundError(Exception):
    pass


# Outcome of confirm_hold.
CONFIRMED = "CONFIRMED"          # hold -> booking created now
ALREADY_DONE = "ALREADY_DONE"    # idempotent: this hold/event was already confirmed
REFUND_REQUIRED = "REFUND_REQUIRED"  # paid, but the hold was no longer valid -> refund


@dataclass
class ConfirmResult:
    outcome: str
    booking: Booking | None


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _lock_keys(seat_ids: list[int]) -> list[str]:
    # Sorted -> overlapping multi-seat operations grab locks in the same order.
    return [f"lock:seat:{sid}" for sid in sorted(set(seat_ids))]


# ---- HOLD ----
def create_hold(db: Session, user_id: int, event_id: int, seat_ids: list[int]) -> Hold:
    """Reserve seats for `user_id` for hold_ttl_seconds. All-or-nothing."""
    seat_ids = sorted(set(seat_ids))
    if not seat_ids:
        raise SeatNotFoundError([])
    if len(seat_ids) > settings.max_seats_per_booking:
        raise TooManySeatsError()

    now = _utcnow()
    expires = now + dt.timedelta(seconds=settings.hold_ttl_seconds)

    with multi_lock(_lock_keys(seat_ids)):
        seats = _select_seats_for_update(db, event_id, seat_ids)
        _ensure_all_exist(seats, seat_ids)

        conflicts = _reclaim_and_find_conflicts(db, seats, now)
        if conflicts:
            db.rollback()
            raise SeatUnavailableError(sorted(conflicts))

        hold = Hold(
            user_id=user_id,
            event_id=event_id,
            status=HoldStatus.ACTIVE,
            expires_at=expires,
            total_cents=sum(s.price_cents for s in seats),
        )
        db.add(hold)
        db.flush()  # assign hold.id

        for s in seats:
            s.status = SeatStatus.HELD
            s.hold_id = hold.id
            s.version += 1
            db.add(HoldItem(hold_id=hold.id, seat_id=s.id, price_cents=s.price_cents))

        deltas = _deltas(seats)
        db.commit()
        db.refresh(hold)
        notify_seat_changes(event_id, deltas)
        return hold


def get_hold(db: Session, hold_id: int) -> Hold | None:
    return db.get(Hold, hold_id)


def is_hold_valid(hold: Hold, now: dt.datetime | None = None) -> bool:
    now = now or _utcnow()
    return hold.status == HoldStatus.ACTIVE and hold.expires_at > now


def expire_hold(db: Session, hold_id: int) -> None:
    """Explicitly expire an ACTIVE hold and release its seats (used when a
    checkout is attempted after the TTL lapsed)."""
    hold = db.get(Hold, hold_id)
    if hold is None or hold.status != HoldStatus.ACTIVE:
        return
    seat_ids = sorted(i.seat_id for i in hold.items)
    with multi_lock(_lock_keys(seat_ids)):
        seats = _select_seats_for_update(db, hold.event_id, seat_ids)
        locked = db.execute(
            select(Hold).where(Hold.id == hold_id).with_for_update().execution_options(populate_existing=True)
        ).scalar_one()
        if locked.status == HoldStatus.ACTIVE:
            _release_seats_of_hold(seats, hold_id)
            locked.status = HoldStatus.EXPIRED
        deltas = _deltas(seats)
        db.commit()
        notify_seat_changes(hold.event_id, deltas)


# ---- CONFIRM (idempotent) ----
def confirm_hold(
    db: Session,
    hold_id: int,
    payment_reference: str | None = None,
    stripe_event_id: str | None = None,
) -> ConfirmResult:
    """Convert a paid, still-valid hold into a booking. Idempotent on both
    `stripe_event_id` (processed-events ledger) and `hold_id` (one booking per
    hold, DB-unique). Returns REFUND_REQUIRED if the hold lapsed before payment
    settled — the caller must refund and must NOT grant seats."""
    hold = db.get(Hold, hold_id)
    if hold is None:
        # Still record the event so a retried webhook for a bogus hold is a no-op.
        if stripe_event_id and _record_processed(db, stripe_event_id):
            db.commit()
        raise HoldNotFoundError()

    seat_ids = sorted(i.seat_id for i in hold.items)

    with multi_lock(_lock_keys(seat_ids)):
        try:
            # Idempotency gate #1: webhook event id already handled?
            if stripe_event_id and not _record_processed(db, stripe_event_id):
                booking = _booking_for_hold(db, hold_id)
                db.rollback()
                return ConfirmResult(ALREADY_DONE, booking)

            # SEATS first, then HOLD (fixed order -> deadlock-free).
            seats = _select_seats_for_update(db, hold.event_id, seat_ids)
            locked_hold = db.execute(
                select(Hold).where(Hold.id == hold_id).with_for_update().execution_options(populate_existing=True)
            ).scalar_one()

            # Idempotency gate #2: this hold already converted.
            if locked_hold.status == HoldStatus.CONVERTED:
                booking = _booking_for_hold(db, hold_id)
                db.commit()
                return ConfirmResult(ALREADY_DONE, booking)

            now = _utcnow()
            still_ours = all(
                s.status == SeatStatus.HELD and s.hold_id == hold_id for s in seats
            )
            if locked_hold.status != HoldStatus.ACTIVE or locked_hold.expires_at <= now or not still_ours:
                # Hold lapsed/abandoned before payment settled. Don't grant seats.
                if locked_hold.status == HoldStatus.ACTIVE:
                    locked_hold.status = HoldStatus.EXPIRED
                _release_seats_of_hold(seats, hold_id)
                locked_hold.stripe_payment_intent = payment_reference or locked_hold.stripe_payment_intent
                deltas = _deltas(seats)
                db.commit()
                notify_seat_changes(locked_hold.event_id, deltas)
                return ConfirmResult(REFUND_REQUIRED, None)

            # Happy path: convert hold -> booking.
            booking = Booking(
                user_id=locked_hold.user_id,
                event_id=locked_hold.event_id,
                hold_id=locked_hold.id,
                status=BookingStatus.CONFIRMED,
                total_cents=locked_hold.total_cents,
                payment_reference=payment_reference,
            )
            db.add(booking)
            db.flush()

            for s in seats:
                s.status = SeatStatus.SOLD
                s.hold_id = None
                s.version += 1
                db.add(BookingItem(booking_id=booking.id, seat_id=s.id, price_cents=s.price_cents, active=True))

            # Issue an e-ticket per seat (atomic with the booking).
            tickets = ticket_service.issue_for_booking(db, booking.id, [s.id for s in seats])

            locked_hold.status = HoldStatus.CONVERTED
            locked_hold.stripe_payment_intent = payment_reference or locked_hold.stripe_payment_intent
            deltas = _deltas(seats)
            event_id = locked_hold.event_id
            user_email = db.get(User, locked_hold.user_id).email
            event = db.get(Event, event_id)
            event_name = event.name if event else f"Event {event_id}"
            ticket_codes = [t.code for t in tickets]
            db.commit()
            db.refresh(booking)
            notify_seat_changes(event_id, deltas)
            # Best-effort confirmation email (never breaks the booking).
            email_service.send_booking_confirmation(user_email, event_name, booking.id, ticket_codes)
            return ConfirmResult(CONFIRMED, booking)

        except IntegrityError:
            # A concurrent confirm won the race (unique on bookings.hold_id or on
            # processed_webhook_events.stripe_event_id). Treat as idempotent dup.
            db.rollback()
            booking = _booking_for_hold(db, hold_id)
            return ConfirmResult(ALREADY_DONE, booking)


# ---- CANCEL ----
def cancel_booking(db: Session, user_id: int, booking_id: int) -> Booking:
    booking = db.get(Booking, booking_id)
    if booking is None or booking.user_id != user_id:
        raise SeatNotFoundError([])
    if booking.status in (BookingStatus.CANCELLED, BookingStatus.REFUNDED):
        return booking

    seat_ids = sorted(item.seat_id for item in booking.items)
    with multi_lock(_lock_keys(seat_ids)):
        seats = _select_seats_for_update(db, booking.event_id, seat_ids)
        for s in seats:
            s.status = SeatStatus.AVAILABLE
            s.hold_id = None
            s.version += 1
        for item in booking.items:
            item.active = False  # frees the partial-unique seat slot for resale
        ticket_service.invalidate_for_booking(db, booking.id)  # void e-tickets
        booking.status = BookingStatus.CANCELLED
        deltas = _deltas(seats)
        db.commit()
        db.refresh(booking)
        notify_seat_changes(booking.event_id, deltas)
    return booking


# ---- SWEEPER ----
def release_expired_holds(db: Session, batch: int = 200) -> int:
    """Reconcile Postgres for holds whose TTL lapsed: HELD seats -> AVAILABLE,
    hold -> EXPIRED. Lazy reclaim in create_hold also covers correctness; this
    keeps the seat map clean for reads and bounds stale state."""
    now = _utcnow()
    expired = db.execute(
        select(Hold)
        .where(Hold.status == HoldStatus.ACTIVE, Hold.expires_at < now)
        .limit(batch)
    ).scalars().all()

    count = 0
    for hold in expired:
        seat_ids = sorted(i.seat_id for i in hold.items)
        with multi_lock(_lock_keys(seat_ids)):
            seats = _select_seats_for_update(db, hold.event_id, seat_ids)
            locked = db.execute(
                select(Hold).where(Hold.id == hold.id).with_for_update().execution_options(populate_existing=True)
            ).scalar_one()
            if locked.status != HoldStatus.ACTIVE:
                db.commit()
                continue
            _release_seats_of_hold(seats, hold.id)
            locked.status = HoldStatus.EXPIRED
            deltas = _deltas(seats)
            db.commit()
            notify_seat_changes(hold.event_id, deltas)
            count += 1
    return count


# ---- internals ----
def _select_seats_for_update(db: Session, event_id: int, seat_ids: list[int]) -> list[Seat]:
    # populate_existing refreshes attributes from the just-locked row, so we never
    # read stale values from the session identity map under a FOR UPDATE lock.
    return list(
        db.execute(
            select(Seat)
            .where(Seat.id.in_(seat_ids), Seat.event_id == event_id)
            .with_for_update()
            .order_by(Seat.id)
            .execution_options(populate_existing=True)
        ).scalars().all()
    )


def _ensure_all_exist(seats: list[Seat], seat_ids: list[int]) -> None:
    found = {s.id for s in seats}
    missing = [sid for sid in seat_ids if sid not in found]
    if missing:
        raise SeatNotFoundError(missing)


def _reclaim_and_find_conflicts(db: Session, seats: list[Seat], now: dt.datetime) -> list[int]:
    """For seats we've locked: reclaim any held by an expired/dead hold, and
    return the ids that are genuinely unavailable (actively held or sold)."""
    held_hold_ids = {s.hold_id for s in seats if s.status == SeatStatus.HELD and s.hold_id is not None}
    holds_map: dict[int, Hold] = {}
    if held_hold_ids:
        rows = db.execute(
            select(Hold).where(Hold.id.in_(held_hold_ids)).with_for_update().execution_options(populate_existing=True)
        ).scalars().all()
        holds_map = {h.id: h for h in rows}

    conflicts: list[int] = []
    for s in seats:
        if s.status == SeatStatus.AVAILABLE:
            continue
        if s.status == SeatStatus.HELD:
            h = holds_map.get(s.hold_id) if s.hold_id is not None else None
            if h is None or h.status != HoldStatus.ACTIVE or h.expires_at <= now:
                if h is not None and h.status == HoldStatus.ACTIVE:
                    h.status = HoldStatus.EXPIRED
                s.status = SeatStatus.AVAILABLE
                s.hold_id = None
                s.version += 1
            else:
                conflicts.append(s.id)
        else:  # SOLD
            conflicts.append(s.id)
    return conflicts


def _release_seats_of_hold(seats: list[Seat], hold_id: int) -> None:
    for s in seats:
        if s.status == SeatStatus.HELD and s.hold_id == hold_id:
            s.status = SeatStatus.AVAILABLE
            s.hold_id = None
            s.version += 1


def _booking_for_hold(db: Session, hold_id: int) -> Booking | None:
    return db.execute(select(Booking).where(Booking.hold_id == hold_id)).scalar_one_or_none()


def _record_processed(db: Session, stripe_event_id: str) -> bool:
    """Returns True if newly recorded (proceed), False if already processed."""
    exists = db.execute(
        select(ProcessedWebhookEvent.id).where(ProcessedWebhookEvent.stripe_event_id == stripe_event_id)
    ).first()
    if exists:
        return False
    db.add(ProcessedWebhookEvent(stripe_event_id=stripe_event_id))
    db.flush()
    return True
