"""Pydantic request/response schemas — the API contract.

Keeping these separate from the ORM models gives a clean boundary: the
database can evolve without leaking columns (e.g. hashed_password) into the API.
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---- Auth ----
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=120)
    # Self-serve role at signup: attendee or organizer (admin is granted, not chosen).
    role: Literal["USER", "ORGANIZER"] = "USER"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    role: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---- Venues ----
class VenueIn(BaseModel):
    name: str = Field(max_length=200)
    address: str = Field(default="", max_length=300)
    city: str = Field(default="", max_length=120)


class VenueOut(VenueIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---- Events / seats ----
class TierIn(BaseModel):
    name: str = Field(max_length=80)
    price_cents: int = Field(ge=0)


class SectionIn(BaseModel):
    name: str = Field(max_length=64)
    rows: int = Field(ge=1, le=100)
    seats_per_row: int = Field(ge=1, le=100)
    tier: str = Field(max_length=80)  # references a TierIn.name


class EventCreate(BaseModel):
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=2000)
    starts_at: dt.datetime
    venue: VenueIn
    tiers: list[TierIn] = Field(min_length=1)
    sections: list[SectionIn] = Field(min_length=1)
    publish: bool = True


class TierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    price_cents: int


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    starts_at: dt.datetime
    status: str
    venue: VenueOut | None = None


class EventDetail(EventOut):
    description: str
    tiers: list[TierOut]
    capacity: int
    available: int


class SeatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    section: str
    seat_number: str
    price_cents: int
    status: str
    version: int


# ---- Holds ----
class SeatSelection(BaseModel):
    event_id: int
    seat_ids: list[int] = Field(min_length=1)


class HoldItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    seat_id: int
    price_cents: int


class HoldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_id: int
    status: str
    expires_at: dt.datetime
    total_cents: int
    items: list[HoldItemOut]


class CheckoutOut(BaseModel):
    hold_id: int
    session_id: str
    checkout_url: str


# ---- Bookings ----
class BookingItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    seat_id: int
    price_cents: int


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    seat_id: int
    code: str
    status: str


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_id: int
    hold_id: int | None
    status: str
    total_cents: int
    created_at: dt.datetime
    items: list[BookingItemOut]
    tickets: list[TicketOut] = []


# ---- Tickets / check-in ----
class CheckinOut(BaseModel):
    code: str
    status: str          # USED on success
    result: str          # "checked_in" | "already_used" | "invalid"
    seat_id: int | None = None


# ---- Analytics ----
class ViewBeacon(BaseModel):
    session_token: str = Field(min_length=8, max_length=64)


class FunnelOut(BaseModel):
    views: int
    holds: int
    paid: int
    view_to_hold: float
    hold_to_paid: float
    view_to_paid: float


# ---- Organizer dashboard ----
class RecentBookingOut(BaseModel):
    booking_id: int
    user_email: str
    seats: int
    total_cents: int
    status: str
    created_at: dt.datetime


class EventStats(BaseModel):
    event_id: int
    name: str
    capacity: int
    sold: int
    held: int
    available: int
    revenue_cents: int
    funnel: FunnelOut
    recent_bookings: list[RecentBookingOut]
