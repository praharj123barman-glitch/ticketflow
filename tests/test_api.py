"""API-level smoke tests covering the auth + booking happy path and the 409 race
outcome through the HTTP layer."""
from __future__ import annotations


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_register_login_me(client):
    r = client.post("/auth/register", json={"email": "a@test.dev", "password": "password123", "full_name": "A"})
    assert r.status_code == 201

    r = client.post("/auth/login", data={"username": "a@test.dev", "password": "password123"})
    assert r.status_code == 200
    token = r.json()["access_token"]

    r = client.get("/auth/me", headers=_auth_header(token))
    assert r.status_code == 200
    assert r.json()["email"] == "a@test.dev"


def test_register_duplicate_email_conflicts(client):
    body = {"email": "dup@test.dev", "password": "password123"}
    assert client.post("/auth/register", json=body).status_code == 201
    assert client.post("/auth/register", json=body).status_code == 409


def test_booking_requires_auth(client, event_with_seats):
    event_id, seat_ids = event_with_seats
    r = client.post("/bookings", json={"event_id": event_id, "seat_ids": [seat_ids[0]]})
    assert r.status_code == 401


def test_book_then_double_book_returns_409(client, auth_token, event_with_seats):
    event_id, seat_ids = event_with_seats
    headers = _auth_header(auth_token)

    r1 = client.post("/bookings", json={"event_id": event_id, "seat_ids": [seat_ids[0]]}, headers=headers)
    assert r1.status_code == 201
    assert r1.json()["status"] == "CONFIRMED"

    r2 = client.post("/bookings", json={"event_id": event_id, "seat_ids": [seat_ids[0]]}, headers=headers)
    assert r2.status_code == 409
    assert r2.json()["detail"]["seats_taken"] == [seat_ids[0]]


def test_seat_map_reflects_booking(client, auth_token, event_with_seats):
    event_id, seat_ids = event_with_seats
    headers = _auth_header(auth_token)
    client.post("/bookings", json={"event_id": event_id, "seat_ids": [seat_ids[0]]}, headers=headers)

    seats = client.get(f"/events/{event_id}/seats").json()
    booked = [s for s in seats if s["id"] == seat_ids[0]][0]
    assert booked["status"] == "BOOKED"


def test_cancel_frees_seat(client, auth_token, event_with_seats):
    event_id, seat_ids = event_with_seats
    headers = _auth_header(auth_token)
    booking = client.post("/bookings", json={"event_id": event_id, "seat_ids": [seat_ids[0]]}, headers=headers).json()

    r = client.post(f"/bookings/{booking['id']}/cancel", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"

    # Seat should be bookable again.
    r2 = client.post("/bookings", json={"event_id": event_id, "seat_ids": [seat_ids[0]]}, headers=headers)
    assert r2.status_code == 201
