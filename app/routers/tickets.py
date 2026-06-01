"""E-ticket retrieval, QR rendering, and single-use check-in."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import get_current_user, require_role
from ..models import Booking, Event, Role, Ticket, User
from ..schemas import CheckinOut, TicketOut
from ..services import ticket_service

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _load_owned(db: Session, code: str, user: User) -> Ticket:
    ticket = db.query(Ticket).filter(Ticket.code == code).first()
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    booking = db.get(Booking, ticket.booking_id)
    if booking is None or booking.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


@router.get("/{code}", response_model=TicketOut)
def get_ticket(code: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Ticket:
    return _load_owned(db, code, user)


@router.get("/{code}/qr.svg")
def get_ticket_qr(code: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    _load_owned(db, code, user)
    return Response(content=ticket_service.qr_svg(code), media_type="image/svg+xml")


@router.post("/{code}/checkin", response_model=CheckinOut)
def checkin(code: str, db: Session = Depends(get_db),
            staff: User = Depends(require_role(Role.ORGANIZER))) -> CheckinOut:
    """Validate + mark a QR as used (one-time). Organizer/admin only."""
    # The check-in actor must own the event the ticket belongs to (admins bypass).
    ticket = db.query(Ticket).filter(Ticket.code == code).first()
    if ticket is not None and staff.role != Role.ADMIN:
        booking = db.get(Booking, ticket.booking_id)
        event = db.get(Event, booking.event_id) if booking else None
        if event is None or event.organizer_id != staff.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your event")

    result, t = ticket_service.checkin(db, code, staff.id)
    http_status = {
        "checked_in": status.HTTP_200_OK,
        "already_used": status.HTTP_409_CONFLICT,
        "invalid": status.HTTP_404_NOT_FOUND,
    }[result]
    payload = CheckinOut(
        code=code,
        status=t.status if t else "UNKNOWN",
        result=result,
        seat_id=t.seat_id if t else None,
    )
    if http_status != status.HTTP_200_OK:
        raise HTTPException(status_code=http_status, detail=payload.model_dump())
    return payload
