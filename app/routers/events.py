"""Event + seat-map routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user
from ..models import Event, Seat, SeatStatus
from ..schemas import EventCreate, EventOut, SeatOut

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventOut])
def list_events(db: Session = Depends(get_db)) -> list[Event]:
    return list(db.execute(select(Event).order_by(Event.starts_at)).scalars().all())


@router.post("", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: EventCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),  # any authenticated user can create in this demo
) -> Event:
    event = Event(name=payload.name, venue=payload.venue, starts_at=payload.starts_at)
    db.add(event)
    db.flush()

    # Materialise the seat map: rows A, B, C... each with N numbered seats.
    seats = []
    for r in range(payload.rows):
        row_label = chr(ord("A") + r) if r < 26 else f"R{r}"
        for n in range(1, payload.seats_per_row + 1):
            seats.append(
                Seat(
                    event_id=event.id,
                    seat_number=f"{row_label}{n}",
                    price_cents=payload.price_cents,
                    status=SeatStatus.AVAILABLE,
                )
            )
    db.add_all(seats)
    db.commit()
    db.refresh(event)
    return event


@router.get("/{event_id}/seats", response_model=list[SeatOut])
def get_seat_map(event_id: int, db: Session = Depends(get_db)) -> list[Seat]:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return list(
        db.execute(select(Seat).where(Seat.event_id == event_id).order_by(Seat.id)).scalars().all()
    )
