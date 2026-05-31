"""Dependency-light HTTP load test (alternative to the k6 script for anyone
without k6 installed). Fires N concurrent users at the SAME seat and reports the
outcome distribution + latency, proving zero double-bookings under real HTTP load.

Usage:
    python loadtest/python_load.py --base-url http://127.0.0.1:8000 --event-id 1 --seat-id 1 --users 100
"""
from __future__ import annotations

import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx


def attempt(base_url: str, event_id: int, seat_id: int, idx: int) -> tuple[int, float]:
    email = f"load_{idx}_{int(time.time()*1000)}@test.dev"
    with httpx.Client(base_url=base_url, timeout=30.0) as c:
        c.post("/auth/register", json={"email": email, "password": "password123"})
        tok = c.post("/auth/login", data={"username": email, "password": "password123"}).json()["access_token"]
        start = time.perf_counter()
        r = c.post(
            "/bookings",
            json={"event_id": event_id, "seat_ids": [seat_id]},
            headers={"Authorization": f"Bearer {tok}"},
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        return r.status_code, elapsed_ms


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--event-id", type=int, default=1)
    p.add_argument("--seat-id", type=int, default=1)
    p.add_argument("--users", type=int, default=100)
    args = p.parse_args()

    print(f"Firing {args.users} concurrent users at event {args.event_id} / seat {args.seat_id} ...")
    codes: list[int] = []
    latencies: list[float] = []

    with ThreadPoolExecutor(max_workers=args.users) as pool:
        futs = [pool.submit(attempt, args.base_url, args.event_id, args.seat_id, i) for i in range(args.users)]
        for f in as_completed(futs):
            code, ms = f.result()
            codes.append(code)
            latencies.append(ms)

    booked = codes.count(201)
    conflict = codes.count(409)
    rate_limited = codes.count(429)
    contention = codes.count(503)
    other = len(codes) - booked - conflict - rate_limited - contention
    latencies.sort()

    def pct(p: float) -> float:
        return latencies[min(len(latencies) - 1, int(len(latencies) * p))]

    print("\n================ RESULTS ================")
    print(f"  concurrent users        : {args.users}")
    print(f"  201 booked (winners)     : {booked}")
    print(f"  409 seat taken           : {conflict}")
    print(f"  429 rate limited         : {rate_limited}")
    print(f"  503 lock contention      : {contention}")
    print(f"  other                    : {other}")
    print(f"  latency p50 / p95 / max  : {pct(0.5):.1f} / {pct(0.95):.1f} / {max(latencies):.1f} ms")
    print(f"  DOUBLE-BOOKINGS          : {max(0, booked - 1)}  (must be 0)")
    print("=========================================")
    assert booked <= 1, "DOUBLE BOOKING DETECTED"
    print("PASS: at most one booking succeeded for the contested seat.")


if __name__ == "__main__":
    main()
