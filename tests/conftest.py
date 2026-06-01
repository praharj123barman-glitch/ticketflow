"""Test fixtures.

These integration tests run against REAL Postgres and Redis (the same engines as
production) because the whole point is to exercise row-level locking — an
in-memory SQLite stub would not reproduce `SELECT ... FOR UPDATE` semantics.

CI provides Postgres + Redis as service containers (see .github/workflows/ci.yml).
Locally, run `docker compose up -d db redis` first.
"""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Event, Seat, SeatStatus
from app.redis_client import redis_client


@pytest.fixture(autouse=True)
def clean_state():
    """Reset DB tables and Redis between tests for isolation."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    redis_client.flushdb()
    yield
    redis_client.flushdb()


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def event_with_seats(db):
    """An event with a small seat map; returns (event_id, [seat_ids])."""
    event = Event(name="Test Show",
                  starts_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1))
    db.add(event)
    db.flush()
    seats = [Seat(event_id=event.id, seat_number=f"A{n}", price_cents=1000,
                  status=SeatStatus.AVAILABLE) for n in range(1, 6)]
    db.add_all(seats)
    db.commit()
    return event.id, [s.id for s in seats]


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_token(client):
    client.post("/auth/register", json={"email": "u1@test.dev", "password": "password123", "full_name": "U1"})
    resp = client.post("/auth/login", data={"username": "u1@test.dev", "password": "password123"})
    return resp.json()["access_token"]
