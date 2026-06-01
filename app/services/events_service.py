"""Event creation (venue + price tiers + sectioned seat map) and public browse."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Event, EventStatus, PriceTier, Seat, SeatStatus, Venue
from .. import schemas


def _row_label(r: int) -> str:
    return chr(ord("A") + r) if r < 26 else f"R{r + 1}"


def create_event(db: Session, organizer_id: int, payload: "schemas.EventCreate") -> Event:
    venue = Venue(name=payload.venue.name, address=payload.venue.address, city=payload.venue.city)
    db.add(venue)
    db.flush()

    event = Event(
        name=payload.name,
        description=payload.description,
        organizer_id=organizer_id,
        venue_id=venue.id,
        starts_at=payload.starts_at,
        status=EventStatus.PUBLISHED if payload.publish else EventStatus.DRAFT,
    )
    db.add(event)
    db.flush()

    tiers: dict[str, PriceTier] = {}
    for t in payload.tiers:
        tier = PriceTier(event_id=event.id, name=t.name, price_cents=t.price_cents)
        db.add(tier)
        tiers[t.name] = tier
    db.flush()

    seats: list[Seat] = []
    for section in payload.sections:
        tier = tiers.get(section.tier)
        if tier is None:
            raise ValueError(f"section '{section.name}' references unknown tier '{section.tier}'")
        for r in range(section.rows):
            row = _row_label(r)
            for n in range(1, section.seats_per_row + 1):
                seats.append(
                    Seat(
                        event_id=event.id,
                        section=section.name,
                        seat_number=f"{section.name}-{row}{n}",
                        tier_id=tier.id,
                        price_cents=tier.price_cents,
                        status=SeatStatus.AVAILABLE,
                    )
                )
    db.add_all(seats)
    db.commit()
    db.refresh(event)
    return event


def search_events(
    db: Session,
    q: str | None = None,
    city: str | None = None,
    date_from: dt.datetime | None = None,
    date_to: dt.datetime | None = None,
) -> list[Event]:
    stmt = select(Event).where(Event.status == EventStatus.PUBLISHED)
    if q:
        stmt = stmt.where(Event.name.ilike(f"%{q}%"))
    if city:
        stmt = stmt.join(Venue, Event.venue_id == Venue.id).where(Venue.city.ilike(f"%{city}%"))
    if date_from:
        stmt = stmt.where(Event.starts_at >= date_from)
    if date_to:
        stmt = stmt.where(Event.starts_at <= date_to)
    return list(db.execute(stmt.order_by(Event.starts_at)).scalars().all())


def capacity_and_available(db: Session, event_id: int) -> tuple[int, int]:
    capacity = db.execute(
        select(func.count(Seat.id)).where(Seat.event_id == event_id)
    ).scalar_one()
    available = db.execute(
        select(func.count(Seat.id)).where(Seat.event_id == event_id, Seat.status == SeatStatus.AVAILABLE)
    ).scalar_one()
    return capacity, available
