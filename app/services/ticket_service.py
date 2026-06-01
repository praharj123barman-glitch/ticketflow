"""E-tickets: issue one per sold seat, render a QR, and validate single-use
check-in. Single-use is enforced at the DB with an atomic conditional UPDATE, so
two concurrent check-ins of the same QR can never both succeed."""
from __future__ import annotations

import datetime as dt
import io
import uuid

import qrcode
import qrcode.image.svg
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import Ticket, TicketStatus


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def issue_for_booking(db: Session, booking_id: int, seat_ids: list[int]) -> list[Ticket]:
    """Create VALID tickets for a confirmed booking. No commit — the caller
    commits so ticket issuance is atomic with the booking."""
    tickets = [
        Ticket(booking_id=booking_id, seat_id=sid, code=uuid.uuid4().hex, status=TicketStatus.VALID)
        for sid in seat_ids
    ]
    db.add_all(tickets)
    return tickets


def invalidate_for_booking(db: Session, booking_id: int) -> None:
    """Void a booking's tickets (on cancel/refund). No commit."""
    db.execute(
        update(Ticket)
        .where(Ticket.booking_id == booking_id, Ticket.status != TicketStatus.USED)
        .values(status=TicketStatus.CANCELLED)
    )


def checkin(db: Session, code: str, checker_id: int) -> tuple[str, Ticket | None]:
    """Atomic single-use check-in. Returns (result, ticket) where result is
    'checked_in' | 'already_used' | 'invalid'."""
    res = db.execute(
        update(Ticket)
        .where(Ticket.code == code, Ticket.status == TicketStatus.VALID)
        .values(status=TicketStatus.USED, used_at=_utcnow(), checked_in_by=checker_id)
    )
    db.commit()

    ticket = db.execute(select(Ticket).where(Ticket.code == code)).scalar_one_or_none()
    if res.rowcount == 1:
        return "checked_in", ticket
    if ticket is None:
        return "invalid", None
    if ticket.status == TicketStatus.USED:
        return "already_used", ticket
    return "invalid", ticket  # CANCELLED or otherwise not valid


def qr_svg(code: str) -> bytes:
    """Render the ticket code as a QR (SVG — pure Python, no Pillow).

    SvgPathImage emits a single <path> with a proper viewBox (and a default black
    fill), so the markup scales cleanly to any size and renders when inlined into
    HTML — unlike the default SvgImage, whose namespaced <svg:rect> + fixed-mm
    sizing renders blank in an HTML (non-XML) document."""
    img = qrcode.make(f"TICKETFLOW:{code}", image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue()
