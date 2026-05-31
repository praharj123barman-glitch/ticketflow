// k6 load test — hammer a single popular seat to demonstrate that the system
// stays correct under contention.
//
// Run against a running stack (docker compose up):
//   1. Seed data:  docker compose exec api python seed.py
//   2. Create an event via the API or use the seeded one (note its id + a seat id).
//   3. k6 run -e BASE_URL=http://localhost -e EVENT_ID=1 -e SEAT_ID=1 loadtest/booking_load_test.js
//
// Expected outcome: exactly ONE 201 (the winner), the rest 409 (seat taken) or
// 429 (rate limited) / 503 (lock contention) — and crucially ZERO cases of two
// 201s for the same seat.

import http from "k6/http";
import { check } from "k6";
import { Counter } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost";
const EVENT_ID = __ENV.EVENT_ID || "1";
const SEAT_ID = __ENV.SEAT_ID || "1";

const booked = new Counter("seat_booked_201");
const conflict = new Counter("seat_conflict_409");

export const options = {
  scenarios: {
    thundering_herd: {
      executor: "per-vu-iterations",
      vus: 100, // 100 virtual users...
      iterations: 1, // ...each making one booking attempt, all at once
      maxDuration: "30s",
    },
  },
};

// Each VU registers its own user in setup-free fashion (unique email per VU+iter).
export default function () {
  const email = `load_${__VU}_${Date.now()}@test.dev`;
  http.post(`${BASE_URL}/auth/register`, JSON.stringify({ email, password: "password123" }), {
    headers: { "Content-Type": "application/json" },
  });

  const loginRes = http.post(`${BASE_URL}/auth/login`, { username: email, password: "password123" });
  const token = loginRes.json("access_token");

  const res = http.post(
    `${BASE_URL}/bookings`,
    JSON.stringify({ event_id: Number(EVENT_ID), seat_ids: [Number(SEAT_ID)] }),
    { headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` } }
  );

  if (res.status === 201) booked.add(1);
  if (res.status === 409) conflict.add(1);

  check(res, {
    "resolved cleanly (201/409/429/503)": (r) => [201, 409, 429, 503].includes(r.status),
  });
}
