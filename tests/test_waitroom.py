"""Virtual waiting room: over-threshold arrivals are queued (not admitted) and
are physically blocked from the hold/booking path until the admitter lets them in.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.services import waitroom


@pytest.fixture
def waitroom_on(monkeypatch):
    """Enable the room with a demo-low threshold (1 active session per event)."""
    monkeypatch.setattr(settings, "waitroom_enabled", True)
    monkeypatch.setattr(settings, "waitroom_active_threshold", 1)
    monkeypatch.setattr(settings, "waitroom_admit_batch", 5)
    yield


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_over_threshold_users_are_queued_not_admitted(client, waitroom_on, event_with_seats):
    event_id, _ = event_with_seats

    results = [client.post(f"/waitroom/{event_id}/join").json() for _ in range(5)]
    admitted = [r for r in results if r["status"] == "admitted"]
    waiting = [r for r in results if r["status"] == "waiting"]

    assert len(admitted) == 1, "only `threshold` users may be admitted immediately"
    assert len(waiting) == 4
    # Positions are assigned in join order (FIFO fairness).
    assert sorted(w["position"] for w in waiting) == [1, 2, 3, 4]
    assert all("estimated_wait_seconds" in w for w in waiting)


def test_waiting_user_is_blocked_from_holds_admitted_user_is_not(client, auth_token, waitroom_on, event_with_seats):
    event_id, seat_ids = event_with_seats
    admitted_token = client.post(f"/waitroom/{event_id}/join").json()["token"]   # 1st -> admitted
    waiting_token = client.post(f"/waitroom/{event_id}/join").json()["token"]    # 2nd -> queued

    h = _auth(auth_token)
    body = {"event_id": event_id, "seat_ids": [seat_ids[0]]}

    # No token at all -> blocked.
    assert client.post("/holds", json=body, headers=h).status_code == 403
    # Queued user -> blocked (cannot reach the booking path).
    blocked = client.post("/holds", json=body, headers={**h, "X-Waitroom-Token": waiting_token})
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["error"] == "waiting_room_required"

    # Admitted user -> allowed.
    ok = client.post("/holds", json=body, headers={**h, "X-Waitroom-Token": admitted_token})
    assert ok.status_code == 201


def test_admitter_promotes_queued_users_when_capacity_frees(client, waitroom_on, event_with_seats, monkeypatch):
    event_id, _ = event_with_seats
    client.post(f"/waitroom/{event_id}/join")                                    # admitted (fills threshold=1)
    waiting_token = client.post(f"/waitroom/{event_id}/join").json()["token"]    # queued
    assert client.get(f"/waitroom/{event_id}/status",
                      headers={"X-Waitroom-Token": waiting_token}).json()["status"] == "waiting"

    # Raise capacity and run one admitter tick -> the queued user is promoted.
    monkeypatch.setattr(settings, "waitroom_active_threshold", 10)
    promoted = waitroom.admit_step()
    assert promoted >= 1
    assert client.get(f"/waitroom/{event_id}/status",
                      headers={"X-Waitroom-Token": waiting_token}).json()["status"] == "admitted"
