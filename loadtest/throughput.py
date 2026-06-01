"""THROUGHPUT load test — realistic, LOW-contention booking load.

This is the opposite of tests/test_booking_concurrency.py (which slams ONE seat
to prove correctness under contention). Here every booking targets a DIFFERENT
seat spread across many seats/events, which is what a real on-sale looks like
once the initial rush settles — so the number it produces is a believable
"bookings/sec at p50/p99" for the system, not a worst-case contention figure.

Each "booking" runs the full real path: POST /holds  ->  POST /holds/{id}/dev-confirm
(the dev-confirm stands in for the Stripe webhook; in offline/test mode it goes
through the exact same idempotent confirm_hold). Latency is measured end-to-end
per booking.

Run the SAME command against the server configured with 1, then 2, then 4
gunicorn workers to produce the worker-count sweep (see README / DEPLOYMENT.md).

Usage:
    python loadtest/throughput.py --base-url http://127.0.0.1:8000 \
        --concurrency 32 --bookings 400
"""
from __future__ import annotations

import argparse
import random
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

_local = threading.local()


def client(base_url: str) -> httpx.Client:
    c = getattr(_local, "client", None)
    if c is None:
        c = httpx.Client(base_url=base_url, timeout=30.0,
                         limits=httpx.Limits(max_connections=4, max_keepalive_connections=4))
        _local.client = c
    return c


def collect_available_seats(base_url: str) -> list[tuple[int, int, int]]:
    """Return [(event_id, seat_id, price_cents)] for every AVAILABLE seat."""
    c = httpx.Client(base_url=base_url, timeout=30.0)
    pool: list[tuple[int, int, int]] = []
    for ev in c.get("/events").json():
        for s in c.get(f"/events/{ev['id']}/seats").json():
            if s["status"] == "AVAILABLE":
                pool.append((ev["id"], s["id"], s["price_cents"]))
    c.close()
    random.shuffle(pool)
    return pool


def make_guest_tokens(base_url: str, n: int) -> list[str]:
    c = httpx.Client(base_url=base_url, timeout=30.0)
    toks = [c.post("/auth/guest").json()["access_token"] for _ in range(n)]
    c.close()
    return toks


def book_one(base_url: str, token: str, event_id: int, seat_id: int) -> tuple[bool, float, int | None]:
    """Full hold -> confirm for one seat. Returns (ok, elapsed_seconds, booking_id)."""
    c = client(base_url)
    h = {"Authorization": f"Bearer {token}"}
    t0 = time.perf_counter()
    try:
        r = c.post("/holds", json={"event_id": event_id, "seat_ids": [seat_id]}, headers=h)
        if r.status_code != 201:
            return False, time.perf_counter() - t0, None
        hold_id = r.json()["id"]
        r2 = c.post(f"/holds/{hold_id}/dev-confirm", headers=h)
        ok = r2.status_code == 200
        bid = r2.json().get("id") if ok else None
        return ok, time.perf_counter() - t0, bid
    except Exception:
        return False, time.perf_counter() - t0, None


def cancel(base_url: str, token: str, booking_id: int) -> None:
    try:
        client(base_url).post(f"/bookings/{booking_id}/cancel", headers={"Authorization": f"Bearer {token}"})
    except Exception:
        pass


def pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    i = min(len(xs) - 1, int(q * len(xs)))
    return xs[i] * 1000  # ms


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--concurrency", type=int, default=32, help="concurrent client requests in flight")
    ap.add_argument("--bookings", type=int, default=400, help="total bookings to complete (timed)")
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--label", default="", help="tag for the result line, e.g. '2 workers'")
    ap.add_argument("--no-cleanup", action="store_true", help="don't cancel bookings afterward")
    args = ap.parse_args()

    print(f"→ collecting available seats from {args.base_url} ...")
    pool = collect_available_seats(args.base_url)
    need = args.bookings + args.warmup
    if len(pool) < need:
        raise SystemExit(f"not enough AVAILABLE seats: have {len(pool)}, need {need}. "
                         f"Seed a bigger load event or lower --bookings.")
    print(f"  {len(pool)} seats available; using {need}")

    tokens = make_guest_tokens(args.base_url, args.concurrency)
    seats = iter(pool)
    booking_ids: list[tuple[str, int]] = []  # (token, booking_id) for cleanup

    # warmup (untimed) — fill pools, JIT, connections. Tracked for cleanup too so
    # repeated sweep runs don't slowly leak seats.
    for i in range(args.warmup):
        ev, sid, _ = next(seats)
        tok = tokens[i % len(tokens)]
        wok, _, wbid = book_one(args.base_url, tok, ev, sid)
        if wok and wbid is not None:
            booking_ids.append((tok, wbid))

    tasks = [(tokens[i % len(tokens)], *next(seats)[:2]) for i in range(args.bookings)]

    print(f"→ running {args.bookings} bookings at concurrency {args.concurrency} ...")
    latencies: list[float] = []
    ok = 0
    t_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool_ex:
        # map each future back to the token it ran with — as_completed reorders,
        # so we must look the token up by future (not by completion index) or the
        # cleanup-cancel would target the wrong owner.
        fut_to_token = {
            pool_ex.submit(book_one, args.base_url, tok, ev, sid): tok
            for (tok, ev, sid) in tasks
        }
        for f in as_completed(fut_to_token):
            success, dt, bid = f.result()
            latencies.append(dt)
            if success:
                ok += 1
                if bid is not None:
                    booking_ids.append((fut_to_token[f], bid))
    wall = time.perf_counter() - t_start

    rps = ok / wall if wall else 0.0
    print("\n================ THROUGHPUT RESULT ================")
    if args.label:
        print(f"config:            {args.label}")
    print(f"concurrency:       {args.concurrency}")
    print(f"bookings ok/total: {ok}/{args.bookings}  ({ok / args.bookings * 100:.1f}%)")
    print(f"wall time:         {wall:.2f}s")
    print(f"throughput:        {rps:.1f} bookings/sec")
    print(f"latency p50:       {pct(latencies, 0.50):.0f} ms")
    print(f"latency p95:       {pct(latencies, 0.95):.0f} ms")
    print(f"latency p99:       {pct(latencies, 0.99):.0f} ms")
    print(f"latency mean:      {statistics.mean(latencies) * 1000:.0f} ms")
    print("===================================================")
    print(f"README ROW | {args.label or 'run'} | {rps:.0f} bookings/sec | "
          f"p50 {pct(latencies, 0.50):.0f}ms | p99 {pct(latencies, 0.99):.0f}ms | {ok}/{args.bookings} ok")

    if not args.no_cleanup:
        print("\n→ cleanup: cancelling bookings to free seats for the next run ...")
        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            list(ex.map(lambda tb: cancel(args.base_url, tb[0], tb[1]), booking_ids))
        print(f"  cancelled {len(booking_ids)} bookings")


if __name__ == "__main__":
    main()
