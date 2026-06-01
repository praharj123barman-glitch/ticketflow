# 🎟️ TicketFlow — Concurrent Event Booking System

[![CI](https://github.com/praharj123barman-glitch/ticketflow/actions/workflows/ci.yml/badge.svg)](https://github.com/praharj123barman-glitch/ticketflow/actions/workflows/ci.yml)

### 🔴 Live demo — one self-hosted HTTPS origin
- **App:** https://ticketflow-prohorj.duckdns.org — demo login `demo@ticketflow.dev` / `password123`
- **API + Swagger:** https://ticketflow-prohorj.duckdns.org/api/docs
- Deployed on AWS EC2: a single nginx serves the React build at `/` and reverse-proxies the API at `/api/*` to gunicorn, with Let's Encrypt HTTPS — see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

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

## Load tests — two different questions

There are **two** load tests because they answer two different questions. They
are reported separately on purpose; conflating them is how you get a misleading
number.

### 1. Correctness under contention (worst case)
*Does the two-layer lock hold when everyone fights for the **same** seat?*
```bash
docker compose up -d --build && docker compose exec api python seed.py
k6 run -e BASE_URL=http://localhost -e EVENT_ID=1 -e SEAT_ID=1 loadtest/booking_load_test.js
# no k6? dependency-light equivalent:
python loadtest/python_load.py --base-url http://127.0.0.1:8000 --event-id 1 --seat-id 1 --users 100
```
**Measured** (100 concurrent users contesting a single seat; single dev uvicorn
worker, local Postgres 16 + Redis):

| Metric | Value |
|---|---|
| Virtual users (concurrent) | 100 |
| Successful bookings (201) for 1 seat | **1** |
| Conflicts (409 seat taken) | **99** |
| **Double-bookings** | **0** ✅ |
| Booking latency p50 / p95 | ~2.8 s / ~3.5 s |

This is a **correctness** stress test: 100 threads serialise on one contested
seat, so latency is high by design. The number that matters is **0 double-bookings**.

### 2. Throughput at low contention (realistic)
*How many bookings/sec can the engine sustain when load is spread across many
seats/events — what a real on-sale looks like once the initial rush settles?*

`loadtest/throughput.py` runs the full **hold → pay → confirm** path for every
booking, each targeting a **different** seat, and self-cleans (cancels its
bookings) so a worker-count sweep is repeatable. Run the same command against the
server configured with 1, 2, then 4 gunicorn workers:
```bash
# on the server, per worker count N:
WEB_CONCURRENCY=N RATE_LIMIT_PER_MINUTE=1000000 docker compose up -d --force-recreate api
docker compose run --rm --no-deps --entrypoint python api \
  loadtest/throughput.py --base-url http://api:8000 --concurrency 32 --bookings 400 --label "N workers"
```

**Measured** — live **AWS EC2 t3.small (2 vCPU, 2 GB)**, real gunicorn → uvicorn
workers behind nginx, Postgres 16 + Redis, single-origin HTTPS. Load client (32
concurrent) co-located on the box; the per-client rate limit was raised for the
run so the benchmark measures the **engine**, not the protective throttle. Each
"booking" = **2 sequential API calls** (`POST /holds` then confirm); latency is
end-to-end per booking.

| gunicorn workers | Throughput | p50 | p99 | success |
|---|---|---|---|---|
| 1 | 31 bookings/sec | 967 ms | 1525 ms | 400/400 |
| 2 | **39 bookings/sec** | 757 ms | 1724 ms | 400/400 |
| 4 | 36 bookings/sec | 805 ms | 1942 ms | 400/400 |

Throughput peaks at **2 workers** — the box has 2 vCPUs, so past that the workers
oversubscribe the cores (and the co-located client competes for CPU). That knee
at `workers ≈ cores` is the expected shape; on a larger instance it moves right.
Every run booked **400/400 with zero double-bookings** — i.e. correctness held at
throughput, not just under the single-seat stress test.

## Demo & sharing checklist
A 10-minute routine to get real visitors and real numbers:

1. **Seed events** (already done on the live box; re-run any time):
   `docker compose exec api python seed.py` — idempotent, adds the 4 events.
2. **Sanity-check the live site**: open the [landing page](https://ticketflow-prohorj.duckdns.org),
   click **Try a sample event** (no signup) and complete one booking end-to-end.
3. **Grab share links** — one per event, they preview with a title + image:
   - `https://ticketflow-prohorj.duckdns.org/e/1` (Coldplay), `/e/2`, `/e/3`, `/e/4`
   - Paste a link into **WhatsApp** and **LinkedIn** to confirm the OpenGraph card
     renders (title, description, the generated `/og/event/{id}.png`). Use the
     [LinkedIn Post Inspector](https://www.linkedin.com/post-inspector/) to force a re-scrape.
4. **Share in a few places** — a class/college WhatsApp group, a LinkedIn post,
   a Reddit/Discord community. Each unique visitor counts once in the funnel.
5. **Watch conversions**: open the [organizer dashboard](https://ticketflow-prohorj.duckdns.org/dashboard)
   (login `organizer@ticketflow.dev` / `password123`), pick an event, and watch
   **Viewed → Held → Paid** climb.

### What to screenshot for the résumé / portfolio
- **The throughput table above** (bookings/sec at p50/p99 across 1/2/4 workers).
- **Organizer dashboard** funnel bars + conversion % once you have real traffic.
- **The live seat map** mid-interaction (a few seats selected/held/sold).
- **A WhatsApp/LinkedIn link preview** showing the per-event OG card.
- **`pytest -v`** output (all tests green) next to the contention-test assertion.

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
In production the built assets are served by the same nginx that proxies the API
(single origin — no `VITE_API_URL` needed, calls go to `/api`). See
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

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
