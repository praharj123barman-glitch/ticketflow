"""SQLAlchemy ORM models — the domain schema.

State machines (see docs/LLD.md):
  * Seat:    AVAILABLE -> HELD -> SOLD, and HELD -> AVAILABLE on expiry/abandon.
             SOLD -> AVAILABLE on cancel/refund.
  * Hold:    ACTIVE -> CONVERTED (paid+confirmed) | EXPIRED (ttl) | CANCELLED.
  * Booking: CONFIRMED -> CANCELLED | REFUNDED.

Concurrency & integrity guards:
  * Seat.status is the source of truth for availability; mutated only inside a
    transaction holding a `SELECT ... FOR UPDATE` row lock (see booking_service).
  * Seat.version is bumped on every mutation (optimistic-read / cache busting).
  * UniqueConstraint(event_id, seat_number) — no duplicate seats per event.
  * Booking.hold_id is UNIQUE — a hold converts to AT MOST ONE booking, so a
    duplicate webhook / double-submit can never create two bookings.
  * Partial unique index on booking_items(seat_id) WHERE active — the DB-level
    FINAL GUARD that a seat can be sold to at most one active booking, even if
    application logic ever slipped.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class SeatStatus:
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    SOLD = "SOLD"


class HoldStatus:
    ACTIVE = "ACTIVE"
    CONVERTED = "CONVERTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class BookingStatus:
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class Role:
    USER = "USER"
    ORGANIZER = "ORGANIZER"
    ADMIN = "ADMIN"


class EventStatus:
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class TicketStatus:
    VALID = "VALID"
    USED = "USED"
    CANCELLED = "CANCELLED"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=Role.USER)
    # Ephemeral "try it without signing up" accounts — created by /auth/guest so
    # strangers can run the full hold->pay->confirm flow with zero friction.
    is_guest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bookings: Mapped[list[Booking]] = relationship(back_populates="user")


class EventView(Base):
    """One row per (event, browser-session) — the top of the conversion funnel.

    A UNIQUE(event_id, session_token) lets the page-view beacon be fired on every
    load while counting each visitor once, so views -> holds -> paid is honest and
    not inflated by polling/refreshes. Holds and paid are derived from the Hold /
    Booking tables directly, so this is the only extra tracking the funnel needs.
    """
    __tablename__ = "event_views"
    __table_args__ = (UniqueConstraint("event_id", "session_token", name="uq_event_view_session"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True, nullable=False)
    session_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(120), nullable=False, default="", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    organizer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    venue_id: Mapped[int | None] = mapped_column(ForeignKey("venues.id"), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=EventStatus.PUBLISHED, index=True)
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    venue: Mapped[Venue | None] = relationship()
    tiers: Mapped[list[PriceTier]] = relationship(back_populates="event", cascade="all, delete-orphan")
    seats: Mapped[list[Seat]] = relationship(back_populates="event", cascade="all, delete-orphan")


class PriceTier(Base):
    __tablename__ = "price_tiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    event: Mapped[Event] = relationship(back_populates="tiers")


class Seat(Base):
    __tablename__ = "seats"
    __table_args__ = (UniqueConstraint("event_id", "seat_number", name="uq_event_seat"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True, nullable=False)
    section: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    seat_number: Mapped[str] = mapped_column(String(32), nullable=False)
    tier_id: Mapped[int | None] = mapped_column(ForeignKey("price_tiers.id"), nullable=True)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=SeatStatus.AVAILABLE, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Points at the hold currently reserving this seat (only while status == HELD).
    hold_id: Mapped[int | None] = mapped_column(ForeignKey("holds.id"), nullable=True, index=True)

    event: Mapped[Event] = relationship(back_populates="seats")


class Hold(Base):
    """A temporary all-or-nothing reservation over a set of seats, with a TTL.
    This is the 'pending order' that a checkout/payment is attached to."""
    __tablename__ = "holds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=HoldStatus.ACTIVE, index=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Payment linkage (set when a checkout session is created / completed).
    stripe_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    stripe_payment_intent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list[HoldItem]] = relationship(back_populates="hold", cascade="all, delete-orphan")


class HoldItem(Base):
    __tablename__ = "hold_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hold_id: Mapped[int] = mapped_column(ForeignKey("holds.id", ondelete="CASCADE"), index=True, nullable=False)
    seat_id: Mapped[int] = mapped_column(ForeignKey("seats.id"), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    hold: Mapped[Hold] = relationship(back_populates="items")


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True, nullable=False)
    # One booking per hold — the idempotency backbone for confirm.
    hold_id: Mapped[int | None] = mapped_column(ForeignKey("holds.id"), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=BookingStatus.CONFIRMED)
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payment_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="bookings")
    items: Mapped[list[BookingItem]] = relationship(back_populates="booking", cascade="all, delete-orphan")
    tickets: Mapped[list[Ticket]] = relationship(back_populates="booking", cascade="all, delete-orphan")


class BookingItem(Base):
    __tablename__ = "booking_items"
    # FINAL GUARD: a seat can appear in at most one ACTIVE booking item. Partial
    # unique index so cancelled/refunded items (active=False) free the seat for
    # resale while history is preserved.
    __table_args__ = (
        Index(
            "uq_active_booking_seat",
            "seat_id",
            unique=True,
            postgresql_where=text("active"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True, nullable=False)
    seat_id: Mapped[int] = mapped_column(ForeignKey("seats.id"), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    booking: Mapped[Booking] = relationship(back_populates="items")


class ProcessedWebhookEvent(Base):
    """Webhook idempotency ledger — a Stripe event id is processed at most once."""
    __tablename__ = "processed_webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stripe_event_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Ticket(Base):
    """One e-ticket per sold seat, with a unique QR code and single-use check-in."""
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True, nullable=False)
    seat_id: Mapped[int] = mapped_column(ForeignKey("seats.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=TicketStatus.VALID, index=True)
    issued_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_in_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    booking: Mapped[Booking] = relationship(back_populates="tickets")
