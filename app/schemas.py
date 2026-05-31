"""Pydantic request/response schemas — the API contract.

Keeping these separate from the ORM models gives a clean boundary: the
database can evolve without leaking columns (e.g. hashed_password) into the API.
"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---- Auth ----
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=120)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---- Events / seats ----
class EventCreate(BaseModel):
    name: str = Field(max_length=200)
    venue: str = Field(default="", max_length=200)
    starts_at: dt.datetime
    rows: int = Field(default=10, ge=1, le=100)
    seats_per_row: int = Field(default=10, ge=1, le=100)
    price_cents: int = Field(default=5000, ge=0)


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    venue: str
    starts_at: dt.datetime


class SeatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    seat_number: str
    price_cents: int
    status: str
    version: int


# ---- Bookings ----
class SeatSelection(BaseModel):
    event_id: int
    seat_ids: list[int] = Field(min_length=1)


class BookingItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    seat_id: int
    price_cents: int


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_id: int
    status: str
    total_cents: int
    created_at: dt.datetime
    items: list[BookingItemOut]


class HoldOut(BaseModel):
    event_id: int
    seat_ids: list[int]
    hold_expires_at: dt.datetime
