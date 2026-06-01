"""Virtual waiting-room endpoints. Public (no auth needed to wait in line) —
fairness is by join time, identity is the issued session token."""
from __future__ import annotations

from fastapi import APIRouter, Header

from ..services import waitroom

router = APIRouter(prefix="/waitroom", tags=["waitroom"])


@router.post("/{event_id}/join")
def join(event_id: int, x_waitroom_token: str | None = Header(default=None)) -> dict:
    """Enter the waiting room. Returns a session token + admitted/waiting status.
    Pass the same token back (header X-Waitroom-Token) to keep your place."""
    return waitroom.join(event_id, x_waitroom_token)


@router.get("/{event_id}/status")
def status(event_id: int, x_waitroom_token: str = Header(...)) -> dict:
    """Live position / ETA, or 'admitted' once it's your turn."""
    return waitroom.status(event_id, x_waitroom_token)
