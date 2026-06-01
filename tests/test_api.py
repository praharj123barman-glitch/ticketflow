"""API-level happy-path tests for the select -> hold -> pay -> confirm flow
(payment runs in offline 'fake' mode, webhook simulated as JSON)."""
from __future__ import annotations


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _completed_event(hold_id: int, event_id: str = "evt_test_1", pi: str = "pi_test_1") -> dict:
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"hold_id": str(hold_id)}, "payment_intent": pi,
                            "client_reference_id": str(hold_id)}},
    }


def test_register_login_me(client):
    assert client.post("/auth/register", json={"email": "a@test.dev", "password": "password123"}).status_code == 201
    token = client.post("/auth/login", data={"username": "a@test.dev", "password": "password123"}).json()["access_token"]
    me = client.get("/auth/me", headers=_auth(token))
    assert me.status_code == 200 and me.json()["email"] == "a@test.dev"


def test_register_duplicate_email_conflicts(client):
    body = {"email": "dup@test.dev", "password": "password123"}
    assert client.post("/auth/register", json=body).status_code == 201
    assert client.post("/auth/register", json=body).status_code == 409


def test_hold_requires_auth(client, event_with_seats):
    event_id, seat_ids = event_with_seats
    assert client.post("/holds", json={"event_id": event_id, "seat_ids": [seat_ids[0]]}).status_code == 401


def test_hold_then_double_hold_conflicts(client, auth_token, event_with_seats):
    event_id, seat_ids = event_with_seats
    h = _auth(auth_token)
    r1 = client.post("/holds", json={"event_id": event_id, "seat_ids": [seat_ids[0]]}, headers=h)
    assert r1.status_code == 201 and r1.json()["status"] == "ACTIVE"
    r2 = client.post("/holds", json={"event_id": event_id, "seat_ids": [seat_ids[0]]}, headers=h)
    assert r2.status_code == 409
    assert r2.json()["detail"]["seats_taken"] == [seat_ids[0]]


def test_checkout_returns_session(client, auth_token, event_with_seats):
    event_id, seat_ids = event_with_seats
    h = _auth(auth_token)
    hold = client.post("/holds", json={"event_id": event_id, "seat_ids": [seat_ids[0]]}, headers=h).json()
    co = client.post(f"/holds/{hold['id']}/checkout", headers=h)
    assert co.status_code == 200
    body = co.json()
    assert body["session_id"] and body["checkout_url"]


def test_full_flow_hold_checkout_webhook_books(client, auth_token, event_with_seats):
    event_id, seat_ids = event_with_seats
    h = _auth(auth_token)
    hold = client.post("/holds", json={"event_id": event_id, "seat_ids": [seat_ids[0]]}, headers=h).json()
    client.post(f"/holds/{hold['id']}/checkout", headers=h)

    # Stripe calls our webhook on payment success.
    wb = client.post("/webhooks/stripe", json=_completed_event(hold["id"]))
    assert wb.status_code == 200 and wb.json()["status"] == "confirmed"

    bookings = client.get("/bookings", headers=h).json()
    assert len(bookings) == 1 and bookings[0]["status"] == "CONFIRMED"

    seats = client.get(f"/events/{event_id}/seats").json()
    assert [s for s in seats if s["id"] == seat_ids[0]][0]["status"] == "SOLD"


def test_cancel_frees_seat(client, auth_token, event_with_seats):
    event_id, seat_ids = event_with_seats
    h = _auth(auth_token)
    hold = client.post("/holds", json={"event_id": event_id, "seat_ids": [seat_ids[0]]}, headers=h).json()
    client.post(f"/holds/{hold['id']}/checkout", headers=h)
    client.post("/webhooks/stripe", json=_completed_event(hold["id"]))
    booking = client.get("/bookings", headers=h).json()[0]

    r = client.post(f"/bookings/{booking['id']}/cancel", headers=h)
    assert r.status_code == 200 and r.json()["status"] in ("CANCELLED", "REFUNDED")

    seats = client.get(f"/events/{event_id}/seats").json()
    assert [s for s in seats if s["id"] == seat_ids[0]][0]["status"] == "AVAILABLE"
