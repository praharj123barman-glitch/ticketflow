"""Seed demo data: an admin, an organizer, an attendee, and a set of realistic
events (so a stranger landing on the site sees a believable line-up, not a single
placeholder). Idempotent — re-running adds only what's missing.

Usage (inside the api container or a local venv):  python seed.py
"""
from __future__ import annotations

import datetime as dt

from app import schemas
from app.core.security import hash_password
from app.database import Base, SessionLocal, engine
from app.models import Event, Role, User
from app.services import events_service

USERS = [
    ("admin@ticketflow.dev", "password123", "Admin", Role.ADMIN),
    ("organizer@ticketflow.dev", "password123", "Organizer", Role.ORGANIZER),
    ("demo@ticketflow.dev", "password123", "Demo User", Role.USER),
]


def _in(days: int, hour: int = 19) -> dt.datetime:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)).replace(
        hour=hour, minute=30, second=0, microsecond=0
    )


# A believable line-up across music / comedy / sport, varied venues + price tiers.
EVENTS = [
    schemas.EventCreate(
        name="Coldplay — Music of the Spheres",
        description="The record-breaking world tour lands in India. One night only, under a sky of LED wristbands.",
        starts_at=_in(30),
        venue=schemas.VenueIn(name="JLN Stadium", address="Lodhi Road", city="Delhi"),
        tiers=[schemas.TierIn(name="VIP", price_cents=750000), schemas.TierIn(name="GA", price_cents=350000)],
        sections=[
            schemas.SectionIn(name="VIP", rows=2, seats_per_row=20, tier="VIP"),
            schemas.SectionIn(name="GA", rows=8, seats_per_row=20, tier="GA"),
        ],
    ),
    schemas.EventCreate(
        name="Arijit Singh Live in Concert",
        description="An intimate evening of the voice behind a generation of love songs, with a full live orchestra.",
        starts_at=_in(14),
        venue=schemas.VenueIn(name="DY Patil Stadium", address="Nerul", city="Mumbai"),
        tiers=[
            schemas.TierIn(name="Front Stage", price_cents=550000),
            schemas.TierIn(name="Lower", price_cents=300000),
            schemas.TierIn(name="Upper", price_cents=150000),
        ],
        sections=[
            schemas.SectionIn(name="Front Stage", rows=3, seats_per_row=18, tier="Front Stage"),
            schemas.SectionIn(name="Lower", rows=5, seats_per_row=22, tier="Lower"),
            schemas.SectionIn(name="Upper", rows=6, seats_per_row=24, tier="Upper"),
        ],
    ),
    schemas.EventCreate(
        name="Sunburn Arena ft. Martin Garrix",
        description="India's biggest electronic music brand returns. Lasers, pyros, and a wall of bass.",
        starts_at=_in(21, hour=20),
        venue=schemas.VenueIn(name="Mahalaxmi Lawns", address="Lower Parel", city="Pune"),
        tiers=[schemas.TierIn(name="Phoenix VIP", price_cents=499900), schemas.TierIn(name="General", price_cents=249900)],
        sections=[
            schemas.SectionIn(name="Phoenix VIP", rows=2, seats_per_row=24, tier="Phoenix VIP"),
            schemas.SectionIn(name="General", rows=10, seats_per_row=30, tier="General"),
        ],
    ),
    schemas.EventCreate(
        name="Zakir Khan — Tathastu",
        description="Stand-up's 'Sakht Launda' with an all-new set of stories about family, longing, and growing up.",
        starts_at=_in(7, hour=18),
        venue=schemas.VenueIn(name="Sir Mukesh Patel Auditorium", address="Vile Parle", city="Mumbai"),
        tiers=[schemas.TierIn(name="Gold", price_cents=199900), schemas.TierIn(name="Silver", price_cents=99900)],
        sections=[
            schemas.SectionIn(name="Gold", rows=6, seats_per_row=16, tier="Gold"),
            schemas.SectionIn(name="Silver", rows=8, seats_per_row=20, tier="Silver"),
        ],
    ),
]


def run() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ids = {}
        for email, pw, name, role in USERS:
            user = db.query(User).filter(User.email == email).first()
            if user is None:
                user = User(email=email, hashed_password=hash_password(pw), full_name=name, role=role)
                db.add(user)
                db.commit()
                db.refresh(user)
                print(f"created {role}: {email} / {pw}")
            ids[role] = user.id

        for payload in EVENTS:
            if db.query(Event).filter(Event.name == payload.name).first() is not None:
                print(f"event '{payload.name}' already exists; skipping")
                continue
            event = events_service.create_event(db, ids[Role.ORGANIZER], payload)
            total = sum(s.rows * s.seats_per_row for s in payload.sections)
            print(f"created event '{event.name}' (id={event.id}) — {total} seats")
    finally:
        db.close()


if __name__ == "__main__":
    run()
