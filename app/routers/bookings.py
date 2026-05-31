"""Booking + hold routes. These are the hot, rate-limited, concurrency-critical
endpoints — they delegate all correctness to booking_service."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.rate_limit import rate_limiter
from ..database import get_db
from ..dependencies import get_current_user
from ..models import Booking, User
from ..schemas import BookingOut, HoldOut, SeatSelection
from ..services import booking_service
from ..services.lock import LockAcquisitionError

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post(
    "/hold",
    response_model=HoldOut,
    dependencies=[Depends(rate_limiter)],
)
def hold(
    payload: SeatSelection,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HoldOut:
    try:
        expires = booking_service.hold_seats(db, user.id, payload.event_id, payload.seat_ids)
    except booking_service.TooManySeatsError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Too many seats requested")
    except booking_service.SeatNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"seats_not_found": e.seat_ids})
    except booking_service.SeatUnavailableError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"seats_taken": e.seat_ids})
    except LockAcquisitionError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="High demand, please retry")
    return HoldOut(event_id=payload.event_id, seat_ids=sorted(set(payload.seat_ids)), hold_expires_at=expires)


@router.post(
    "",
    response_model=BookingOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limiter)],
)
def create_booking(
    payload: SeatSelection,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Booking:
    try:
        return booking_service.confirm_booking(db, user.id, payload.event_id, payload.seat_ids)
    except booking_service.TooManySeatsError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Too many seats requested")
    except booking_service.SeatNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"seats_not_found": e.seat_ids})
    except booking_service.SeatUnavailableError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"seats_taken": e.seat_ids})
    except LockAcquisitionError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="High demand, please retry")


@router.get("", response_model=list[BookingOut])
def my_bookings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Booking]:
    return list(
        db.execute(
            select(Booking).where(Booking.user_id == user.id).order_by(Booking.created_at.desc())
        ).scalars().all()
    )


@router.post("/{booking_id}/cancel", response_model=BookingOut)
def cancel(
    booking_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Booking:
    try:
        return booking_service.cancel_booking(db, user.id, booking_id)
    except booking_service.SeatNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
