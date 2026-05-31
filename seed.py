"""Seed the database with a demo user and a sample event + seat map.

Usage (inside the api container or a local venv):
    python seed.py
"""
from __future__ import annotations

import datetime as dt

from app.core.security import hash_password
from app.database import Base, SessionLocal, engine
from app.models import Event, Seat, SeatStatus, User

DEMO_EMAIL = "demo@ticketflow.dev"
DEMO_PASSWORD = "password123"


def run() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == DEMO_EMAIL).first() is None:
            db.add(User(email=DEMO_EMAIL, hashed_password=hash_password(DEMO_PASSWORD), full_name="Demo User"))
            db.commit()
            print(f"created demo user: {DEMO_EMAIL} / {DEMO_PASSWORD}")

        if db.query(Event).first() is None:
            event = Event(
                name="Coldplay — Music of the Spheres",
                venue="JLN Stadium, Delhi",
                starts_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30),
            )
            db.add(event)
            db.flush()
            seats = []
            for r in range(10):              # rows A..J
                row = chr(ord("A") + r)
                for n in range(1, 21):       # 20 seats per row -> 200 seats
                    seats.append(
                        Seat(
                            event_id=event.id,
                            seat_number=f"{row}{n}",
                            price_cents=750000 if r < 2 else 350000,  # front rows pricier
                            status=SeatStatus.AVAILABLE,
                        )
                    )
            db.add_all(seats)
            db.commit()
            print(f"created event '{event.name}' with {len(seats)} seats (id={event.id})")
        else:
            print("event already exists; skipping")
    finally:
        db.close()


if __name__ == "__main__":
    run()
