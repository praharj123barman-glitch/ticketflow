"""Organizer dashboard: events I own + per-event sales/revenue/recent bookings."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_role
from ..models import Booking, BookingStatus, Event, Role, Seat, SeatStatus, User
from ..schemas import EventOut, EventStats, FunnelOut, RecentBookingOut
from ..services import analytics_service

router = APIRouter(prefix="/organizer", tags=["organizer"])


@router.get("/events", response_model=list[EventOut])
def my_events(db: Session = Depends(get_db), me: User = Depends(require_role(Role.ORGANIZER))) -> list[Event]:
    stmt = select(Event).order_by(Event.starts_at.desc())
    if me.role != Role.ADMIN:
        stmt = stmt.where(Event.organizer_id == me.id)
    return list(db.execute(stmt).scalars().all())


@router.get("/events/{event_id}/stats", response_model=EventStats)
def event_stats(event_id: int, db: Session = Depends(get_db),
                me: User = Depends(require_role(Role.ORGANIZER))) -> EventStats:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Event not found")
    if me.role != Role.ADMIN and event.organizer_id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your event")

    def seat_count(*statuses: str) -> int:
        return db.execute(
            select(func.count(Seat.id)).where(Seat.event_id == event_id, Seat.status.in_(statuses))
        ).scalar_one()

    capacity = db.execute(select(func.count(Seat.id)).where(Seat.event_id == event_id)).scalar_one()
    sold = seat_count(SeatStatus.SOLD)
    held = seat_count(SeatStatus.HELD)
    available = seat_count(SeatStatus.AVAILABLE)

    revenue = db.execute(
        select(func.coalesce(func.sum(Booking.total_cents), 0)).where(
            Booking.event_id == event_id, Booking.status == BookingStatus.CONFIRMED
        )
    ).scalar_one()

    recent_rows = db.execute(
        select(Booking, User.email)
        .join(User, Booking.user_id == User.id)
        .where(Booking.event_id == event_id)
        .order_by(Booking.created_at.desc())
        .limit(10)
    ).all()
    recent = [
        RecentBookingOut(
            booking_id=b.id, user_email=email, seats=len(b.items),
            total_cents=b.total_cents, status=b.status, created_at=b.created_at,
        )
        for (b, email) in recent_rows
    ]

    f = analytics_service.funnel_for_event(db, event_id)
    funnel = FunnelOut(
        views=f.views, holds=f.holds, paid=f.paid,
        view_to_hold=f.view_to_hold, hold_to_paid=f.hold_to_paid, view_to_paid=f.view_to_paid,
    )

    return EventStats(
        event_id=event_id, name=event.name, capacity=capacity, sold=sold, held=held,
        available=available, revenue_cents=revenue, funnel=funnel, recent_bookings=recent,
    )
