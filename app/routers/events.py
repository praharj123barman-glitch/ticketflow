"""Event browse/detail (public) + event creation (organizers only)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_role
from ..models import Event, Role, User
from ..schemas import EventCreate, EventDetail, EventOut, SeatOut, VenueOut, ViewBeacon
from ..services import analytics_service, events_service, seatcache

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventOut])
def list_events(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None, description="search event name"),
    city: str | None = Query(default=None),
    date_from: dt.datetime | None = Query(default=None),
    date_to: dt.datetime | None = Query(default=None),
) -> list[Event]:
    return events_service.search_events(db, q=q, city=city, date_from=date_from, date_to=date_to)


@router.post("", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: EventCreate,
    db: Session = Depends(get_db),
    organizer: User = Depends(require_role(Role.ORGANIZER)),
) -> Event:
    try:
        return events_service.create_event(db, organizer.id, payload)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{event_id}", response_model=EventDetail)
def event_detail(event_id: int, db: Session = Depends(get_db)) -> EventDetail:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    capacity, available = events_service.capacity_and_available(db, event_id)
    return EventDetail(
        id=event.id,
        name=event.name,
        starts_at=event.starts_at,
        status=event.status,
        venue=VenueOut.model_validate(event.venue) if event.venue else None,
        description=event.description,
        tiers=event.tiers,
        capacity=capacity,
        available=available,
    )


@router.get("/{event_id}/seats", response_model=list[SeatOut])
def get_seat_map(event_id: int, db: Session = Depends(get_db)) -> list[dict]:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return seatcache.get_seat_map(db, event_id)


@router.post("/{event_id}/view", status_code=status.HTTP_204_NO_CONTENT)
def record_view(event_id: int, beacon: ViewBeacon, db: Session = Depends(get_db)) -> None:
    """Public funnel beacon — counts a unique visitor for an event (top of the
    viewed -> held -> paid funnel). Deduped per browser session; no auth so it
    fires for anonymous visitors too."""
    if db.get(Event, event_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    analytics_service.record_view(db, event_id, beacon.session_token)
