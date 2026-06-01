"""Booking read + cancel routes. Bookings are now CREATED only via the payment
webhook (see routers/webhooks.py → booking_service.confirm_hold). There is no
'commit on click' endpoint anymore — seats are reserved via /holds first."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import Booking, BookingStatus, User
from ..schemas import BookingOut
from ..services import booking_service, payment_service

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.get("", response_model=list[BookingOut])
def my_bookings(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[Booking]:
    return list(
        db.execute(
            select(Booking).where(Booking.user_id == user.id).order_by(Booking.created_at.desc())
        ).scalars().all()
    )


@router.post("/{booking_id}/cancel", response_model=BookingOut)
def cancel(booking_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Booking:
    try:
        booking = booking_service.cancel_booking(db, user.id, booking_id)
    except booking_service.SeatNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Booking not found")

    # Refund the captured payment if there was one (no-op in offline dev mode).
    if booking.status == BookingStatus.CANCELLED and booking.payment_reference:
        payment_service.refund(booking.payment_reference)
        booking.status = BookingStatus.REFUNDED
        db.commit()
        db.refresh(booking)
    return booking
