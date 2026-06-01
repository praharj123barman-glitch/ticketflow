"""Lightweight conversion-funnel analytics: viewed -> held -> paid, per event.

Only the *view* stage needs explicit tracking (a per-session beacon, deduped by a
UNIQUE(event_id, session_token)). The *held* and *paid* stages are derived
straight from the Hold and Booking tables, so the funnel stays honest with almost
no extra write path on the hot booking flow.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import Booking, EventView, Hold


def record_view(db: Session, event_id: int, session_token: str) -> None:
    """Count a unique visitor for an event. Idempotent per (event, session) via
    INSERT ... ON CONFLICT DO NOTHING, so firing the beacon on every page load
    never double-counts a refresh or a poll."""
    stmt = (
        pg_insert(EventView)
        .values(event_id=event_id, session_token=session_token[:64])
        .on_conflict_do_nothing(constraint="uq_event_view_session")
    )
    db.execute(stmt)
    db.commit()


@dataclass
class Funnel:
    views: int          # distinct visitor sessions
    holds: int          # holds started (reservations)
    paid: int           # bookings confirmed
    view_to_hold: float  # % of viewers who reserved a seat
    hold_to_paid: float  # % of reservations that paid
    view_to_paid: float  # overall conversion


def _pct(num: int, den: int) -> float:
    return round(100.0 * num / den, 1) if den else 0.0


def funnel_for_event(db: Session, event_id: int) -> Funnel:
    views = db.execute(
        select(func.count(EventView.id)).where(EventView.event_id == event_id)
    ).scalar_one()
    holds = db.execute(
        select(func.count(Hold.id)).where(Hold.event_id == event_id)
    ).scalar_one()
    paid = db.execute(
        select(func.count(Booking.id)).where(Booking.event_id == event_id)
    ).scalar_one()
    return Funnel(
        views=views, holds=holds, paid=paid,
        view_to_hold=_pct(holds, views),
        hold_to_paid=_pct(paid, holds),
        view_to_paid=_pct(paid, views),
    )
