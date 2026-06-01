"""Hold + checkout routes — the first half of the select -> hold -> pay -> confirm
lifecycle. Holds are the hot, concurrency-critical, rate-limited path."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ..core.rate_limit import rate_limiter
from ..database import get_db
from ..dependencies import get_current_user
from ..models import Hold, Seat, User
from ..schemas import BookingOut, CheckoutOut, HoldOut, SeatSelection
from ..services import booking_service, payment_service, waitroom
from ..services.lock import LockAcquisitionError

router = APIRouter(prefix="/holds", tags=["holds"])


def _require_waitroom(event_id: int, token: str | None) -> None:
    """Enforce that the caller passed the waiting room (when enabled)."""
    try:
        waitroom.ensure_admitted(event_id, token)
    except waitroom.WaitroomError:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"error": "waiting_room_required", "event_id": event_id},
        )


@router.post("", response_model=HoldOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(rate_limiter)])
def create_hold(
    payload: SeatSelection,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    x_waitroom_token: str | None = Header(default=None),
) -> Hold:
    _require_waitroom(payload.event_id, x_waitroom_token)
    try:
        return booking_service.create_hold(db, user.id, payload.event_id, payload.seat_ids)
    except booking_service.TooManySeatsError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Too many seats requested")
    except booking_service.SeatNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"seats_not_found": e.seat_ids})
    except booking_service.SeatUnavailableError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"seats_taken": e.seat_ids})
    except LockAcquisitionError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="High demand, please retry")


@router.get("/{hold_id}", response_model=HoldOut)
def get_hold(hold_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Hold:
    hold = booking_service.get_hold(db, hold_id)
    if hold is None or hold.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Hold not found")
    return hold


@router.post("/{hold_id}/checkout", response_model=CheckoutOut, dependencies=[Depends(rate_limiter)])
def checkout(
    hold_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    x_waitroom_token: str | None = Header(default=None),
) -> CheckoutOut:
    hold = booking_service.get_hold(db, hold_id)
    if hold is None or hold.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Hold not found")
    _require_waitroom(hold.event_id, x_waitroom_token)

    # The hold MUST still be valid at checkout time — if the TTL lapsed mid-flow,
    # release it and fail cleanly. No session is created, so nothing is charged.
    if not booking_service.is_hold_valid(hold, dt.datetime.now(dt.timezone.utc)):
        booking_service.expire_hold(db, hold_id)
        raise HTTPException(status.HTTP_410_GONE, detail="Hold expired — please reselect your seats")

    # Build line items (seat label + price) for the Checkout Session.
    seats = {s.id: s for s in db.query(Seat).filter(Seat.id.in_([i.seat_id for i in hold.items])).all()}
    line_items = [
        (f"Seat {seats[i.seat_id].seat_number}" if i.seat_id in seats else f"Seat {i.seat_id}", i.price_cents)
        for i in hold.items
    ]

    session_id, url = payment_service.create_checkout_session(hold_id, line_items)
    hold.stripe_session_id = session_id
    db.commit()
    return CheckoutOut(hold_id=hold_id, session_id=session_id, checkout_url=url)


@router.post("/{hold_id}/dev-confirm", response_model=BookingOut)
def dev_confirm(
    hold_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BookingOut:
    """DEV ONLY: simulate the Stripe webhook so the full pay -> confirm beat can
    run locally without keys. Returns 404 when real Stripe is configured (prod
    confirms exclusively via the signature-verified webhook). The conversion
    itself goes through the same idempotent booking_service.confirm_hold path."""
    if payment_service.stripe_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")

    hold = booking_service.get_hold(db, hold_id)
    if hold is None or hold.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Hold not found")

    try:
        result = booking_service.confirm_hold(
            db, hold_id,
            payment_reference=f"pi_fake_{hold_id}",
            stripe_event_id=f"evt_fake_{hold_id}",
        )
    except booking_service.HoldNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Hold not found")

    if result.outcome == booking_service.REFUND_REQUIRED or result.booking is None:
        raise HTTPException(status.HTTP_410_GONE, detail="Hold expired — please reselect your seats")
    return result.booking
