# 🎟️ TicketFlow — Concurrent Event Booking System

[![CI](https://github.com/praharj123barman-glitch/ticketflow/actions/workflows/ci.yml/badge.svg)](https://github.com/praharj123barman-glitch/ticketflow/actions/workflows/ci.yml)

A production-shaped backend for booking event tickets where thousands of users
compete for the **same limited seats** at once. The engineering centrepiece is a
**two-layer concurrency-control mechanism** (Redis distributed lock + PostgreSQL
`SELECT ... FOR UPDATE`) that makes double-booking **impossible** under load —
verified by a concurrency test that fires 50 parallel requests at a single seat.

> Tech: **FastAPI · PostgreSQL · Redis · SQLAlchemy 2.0 · Docker · nginx · gunicorn · GitHub Actions**

---

## Why this project exists
Most CRUD apps never hit a real systems problem. Ticket booking does: it forces
you to solve **race conditions, distributed locking, transaction isolation,
deadlock avoidance, rate limiting, and horizontal-scale design** — exactly the
topics a backend/SDE interview drills into. See [`docs/HLD.md`](docs/HLD.md) and
[`docs/LLD.md`](docs/LLD.md) for the full system design.

## Architecture
```
Client ──HTTPS──▶ nginx ──HTTP──▶ gunicorn (uvicorn workers) ──▶ FastAPI
                                                                   ├──▶ PostgreSQL   (source of truth, row locks)
                                                                   └──▶ Redis        (distributed locks + rate limit)
```

## The hard problem — preventing double-booking
1. **Redis distributed lock** (`SET NX PX` + token-checked Lua release, TTL
   safety net) — cheap, cross-worker contention control *before* the DB.
2. **Postgres row lock** (`SELECT ... FOR UPDATE` inside a transaction) — the
   authoritative guarantee; availability is re-validated *inside* the lock.
3. **Ordered locking** (sorted seat ids) — multi-seat bookings can't deadlock.

Full walkthrough with sequence diagrams: [`docs/HLD.md`](docs/HLD.md).

---

## Quick start (Docker — recommended)
```bash
# 1. Bring up the full stack: nginx + api + postgres + redis
docker compose up -d --build

# 2. Seed a demo event (200 seats) + demo user
docker compose exec api python seed.py

# 3. Open the interactive API docs
open http://localhost/docs        # Swagger UI via nginx
```

Demo credentials: `demo@ticketflow.dev` / `password123`.

### Try the booking flow
```bash
# register + login
curl -s -X POST localhost/auth/register -H 'content-type: application/json' \
  -d '{"email":"me@x.dev","password":"password123"}'
TOKEN=$(curl -s -X POST localhost/auth/login \
  -d 'username=me@x.dev&password=password123' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# see seats, then book seat id 1 of event 1
curl -s localhost/events/1/seats | head
curl -s -X POST localhost/bookings -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"event_id":1,"seat_ids":[1]}'
```

## Local dev (without Docker)
Requires Postgres + Redis reachable (e.g. `docker compose up -d db redis`):
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python seed.py
uvicorn app.main:app --reload
```

## Tests
The tests run against **real Postgres + Redis** (an in-memory stub can't
reproduce `FOR UPDATE`). Start them first, then:
```bash
docker compose up -d db redis
pytest -v
```
Headline test (`tests/test_booking_concurrency.py`): 50 threads race for one seat
→ asserts **exactly 1 booking, 49 rejected, 0 double-bookings**.

## Load test (k6)
```bash
docker compose up -d --build
docker compose exec api python seed.py
k6 run -e BASE_URL=http://localhost -e EVENT_ID=1 -e SEAT_ID=1 loadtest/booking_load_test.js
```
Expected: one `seat_booked_201`, the rest `409/429/503`, never two 201s for the
same seat.

No k6? A dependency-light equivalent ships in the repo:
```bash
python loadtest/python_load.py --base-url http://127.0.0.1:8000 --event-id 1 --seat-id 1 --users 100
```

**Measured result** (100 concurrent users contesting a single seat; single dev
uvicorn worker, local Postgres 16 + Redis):

| Metric | Value |
|---|---|
| Virtual users (concurrent) | 100 |
| Successful bookings (201) for 1 seat | **1** |
| Conflicts (409 seat taken) | **99** |
| **Double-bookings** | **0** ✅ |
| Booking latency p50 / p95 | ~2.8 s / ~3.5 s* |

\* Latency reflects 100 threads serialising on one contested seat through a
single dev worker (plus per-user bcrypt register/login in the harness). It is a
correctness stress test, not a throughput benchmark — production runs multiple
gunicorn workers behind nginx and contention is spread across thousands of seats.

## Production deploy (the L2 way, on an AWS EC2 / GCP VM)
```bash
# on an Ubuntu VM with Docker installed
git clone <your-repo> && cd ticketflow
echo "JWT_SECRET=$(openssl rand -hex 32)" > .env
docker compose up -d --build
docker compose exec api python seed.py
# point a domain at the VM, add TLS certs (certbot) and enable the 443 block in nginx/nginx.conf
```
- `gunicorn` runs multiple `uvicorn` workers (config in `gunicorn_conf.py`).
- `nginx` is the public entrypoint (TLS, edge rate limiting, real-IP forwarding).
- Health: `GET /health` (liveness), `GET /ready` (DB + Redis reachability).

## Database migrations (Alembic)
The schema is owned by Alembic migrations. The Docker entrypoint runs
`alembic upgrade head` automatically before starting gunicorn; in dev the app
also auto-creates tables for convenience (gated to `ENVIRONMENT != production`).
```bash
alembic revision --autogenerate -m "describe change"   # create a migration
alembic upgrade head                                    # apply
alembic downgrade -1                                    # roll back one
```

## Frontend (React seat picker)
A small Vite + React + TypeScript + Tailwind + Framer Motion client lives in
[`frontend/`](frontend/). It renders the live seat map, lets you select and book
seats, shows your bookings, and polls every few seconds so you can watch seats
get taken in real time.
```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 (proxies /api -> the FastAPI server)
```
In production, build static assets (`npm run build`) and set `VITE_API_URL` to
the public API origin.

## Project layout
```
app/            application code (see docs/LLD.md §6 for the full map)
alembic/        database migrations (versioned schema)
frontend/       React + Vite seat-picker UI
tests/          pytest suite incl. the concurrency test
loadtest/       k6 script + dependency-light Python load runner
nginx/          reverse-proxy config
docs/           HLD.md + LLD.md (system design)
Dockerfile · docker-compose.yml · gunicorn_conf.py · entrypoint.sh · .github/workflows/ci.yml
```

## Roadmap to L4 (live users)
- Async payment confirmation (queue + idempotency keys).
- Virtual waiting room for on-sale spikes.
- Seat-map Redis cache with version-based invalidation.
- Alembic migrations + managed Postgres (RDS Multi-AZ) and Redis replication.
- Minimal React seat-picker frontend, then ship it and gather real bookings.
