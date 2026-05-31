"""SQLAlchemy ORM models — the domain schema.

Design notes (these matter for the LLD / interview story):
  * Seat.status is the single source of truth for availability. It is mutated
    only inside a transaction that holds a `SELECT ... FOR UPDATE` row lock.
  * Seat.version is an optimistic-concurrency column. We use pessimistic
    locking on the hot booking path, but the version column lets read-heavy
    clients detect stale seat maps and is the basis for the alternative
    optimistic strategy discussed in docs/LLD.md.
  * UniqueConstraint(event_id, seat_number) guarantees no duplicate seats per
    event at the database level — defence in depth beyond application checks.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class SeatStatus:
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    BOOKED = "BOOKED"


class BookingStatus:
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bookings: Mapped[list[Booking]] = relationship(back_populates="user")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    venue: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    seats: Mapped[list[Seat]] = relationship(back_populates="event", cascade="all, delete-orphan")


class Seat(Base):
    __tablename__ = "seats"
    __table_args__ = (UniqueConstraint("event_id", "seat_number", name="uq_event_seat"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True, nullable=False)
    seat_number: Mapped[str] = mapped_column(String(16), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=SeatStatus.AVAILABLE, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Hold metadata — populated only while status == HELD
    held_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    hold_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    event: Mapped[Event] = relationship(back_populates="seats")


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=BookingStatus.CONFIRMED)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="bookings")
    items: Mapped[list[BookingItem]] = relationship(back_populates="booking", cascade="all, delete-orphan")


class BookingItem(Base):
    __tablename__ = "booking_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True, nullable=False)
    seat_id: Mapped[int] = mapped_column(ForeignKey("seats.id"), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    booking: Mapped[Booking] = relationship(back_populates="items")
