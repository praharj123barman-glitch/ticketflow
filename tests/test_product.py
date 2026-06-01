"""Product-layer tests: RBAC + multi-event, e-tickets, the REQUIRED cancel->seat
-release path, and the REQUIRED QR single-use check-in."""
from __future__ import annotations

from app.services.email_service import outbox

EVENT_PAYLOAD = {
    "name": "My Show",
    "description": "A great night",
    "starts_at": "2027-01-01T20:00:00Z",
    "venue": {"name": "Indira Hall", "address": "1 Main St", "city": "Delhi"},
    "tiers": [{"name": "VIP", "price_cents": 5000}, {"name": "GA", "price_cents": 1500}],
    "sections": [
        {"name": "VIP", "rows": 1, "seats_per_row": 2, "tier": "VIP"},
        {"name": "GA", "rows": 1, "seats_per_row": 3, "tier": "GA"},
    ],
}


def _auth(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


def _register_login(client, email: str, role: str = "USER") -> str:
    client.post("/auth/register", json={"email": email, "password": "password123", "role": role})
    return client.post("/auth/login", data={"username": email, "password": "password123"}).json()["access_token"]


def _create_event(client, org_token: str) -> int:
    r = client.post("/events", json=EVENT_PAYLOAD, headers=_auth(org_token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _book_first_available(client, user_token: str, event_id: int):
    """Drive the real hold -> checkout -> webhook-confirm flow; return (seat_id, booking)."""
    h = _auth(user_token)
    seats = client.get(f"/events/{event_id}/seats").json()
    sid = next(s["id"] for s in seats if s["status"] == "AVAILABLE")
    hold = client.post("/holds", json={"event_id": event_id, "seat_ids": [sid]}, headers=h).json()
    client.post(f"/holds/{hold['id']}/checkout", headers=h)
    event = {
        "id": f"evt_{event_id}_{sid}",
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"hold_id": str(hold["id"])}, "payment_intent": "pi_test"}},
    }
    assert client.post("/webhooks/stripe", json=event).json()["status"] == "confirmed"
    booking = client.get("/bookings", headers=h).json()[0]
    return sid, booking


# ---- RBAC + multi-event ----
def test_only_organizers_can_create_events(client):
    user = _register_login(client, "u@test.dev", "USER")
    assert client.post("/events", json=EVENT_PAYLOAD, headers=_auth(user)).status_code == 403
    org = _register_login(client, "o@test.dev", "ORGANIZER")
    assert client.post("/events", json=EVENT_PAYLOAD, headers=_auth(org)).status_code == 201


def test_event_detail_capacity_tiers_and_search(client):
    org = _register_login(client, "o2@test.dev", "ORGANIZER")
    eid = _create_event(client, org)

    detail = client.get(f"/events/{eid}").json()
    assert detail["capacity"] == 5 and detail["available"] == 5      # 2 VIP + 3 GA
    assert {t["name"] for t in detail["tiers"]} == {"VIP", "GA"}
    assert detail["venue"]["city"] == "Delhi"

    assert any(e["id"] == eid for e in client.get("/events", params={"city": "Delhi"}).json())
    assert all(e["id"] != eid for e in client.get("/events", params={"city": "Atlantis"}).json())


# ---- e-tickets + email ----
def test_confirmed_booking_issues_tickets_and_emails(client):
    outbox.clear()
    org = _register_login(client, "o3@test.dev", "ORGANIZER")
    eid = _create_event(client, org)
    user = _register_login(client, "buyer3@test.dev")
    _sid, booking = _book_first_available(client, user, eid)

    assert len(booking["tickets"]) == 1
    code = booking["tickets"][0]["code"]
    assert booking["tickets"][0]["status"] == "VALID"
    # QR renders as SVG
    qr = client.get(f"/tickets/{code}/qr.svg", headers=_auth(user))
    assert qr.status_code == 200 and qr.headers["content-type"].startswith("image/svg")
    # confirmation email landed in the dev outbox
    assert any(str(booking["id"]) in m["subject"] for m in outbox)


# ---- REQUIRED: cancel -> seat release ----
def test_cancel_releases_seat_and_voids_tickets(client):
    org = _register_login(client, "o4@test.dev", "ORGANIZER")
    eid = _create_event(client, org)
    user = _register_login(client, "buyer4@test.dev")
    sid, booking = _book_first_available(client, user, eid)

    # seat is SOLD after booking
    seats = client.get(f"/events/{eid}/seats").json()
    assert next(s for s in seats if s["id"] == sid)["status"] == "SOLD"

    # cancel
    r = client.post(f"/bookings/{booking['id']}/cancel", headers=_auth(user))
    assert r.status_code == 200 and r.json()["status"] in ("CANCELLED", "REFUNDED")

    # seat released back to AVAILABLE...
    seats = client.get(f"/events/{eid}/seats").json()
    assert next(s for s in seats if s["id"] == sid)["status"] == "AVAILABLE"
    # ...and the e-ticket is voided
    after = next(b for b in client.get("/bookings", headers=_auth(user)).json() if b["id"] == booking["id"])
    assert all(t["status"] == "CANCELLED" for t in after["tickets"])


# ---- REQUIRED: QR single-use check-in ----
def test_qr_checkin_is_single_use_and_organizer_only(client):
    org = _register_login(client, "o5@test.dev", "ORGANIZER")
    eid = _create_event(client, org)
    user = _register_login(client, "buyer5@test.dev")
    _sid, booking = _book_first_available(client, user, eid)
    code = booking["tickets"][0]["code"]

    # an attendee cannot check tickets in (role gate)
    assert client.post(f"/tickets/{code}/checkin", headers=_auth(user)).status_code == 403

    # organizer checks in -> success, ticket USED
    r1 = client.post(f"/tickets/{code}/checkin", headers=_auth(org))
    assert r1.status_code == 200 and r1.json()["result"] == "checked_in" and r1.json()["status"] == "USED"

    # second scan of the SAME QR -> rejected (single use)
    r2 = client.post(f"/tickets/{code}/checkin", headers=_auth(org))
    assert r2.status_code == 409 and r2.json()["detail"]["result"] == "already_used"
