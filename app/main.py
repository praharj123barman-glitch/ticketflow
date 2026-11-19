"""FastAPI application entrypoint.

Responsibilities:
  * Wire routers.
  * On startup: ensure schema exists and launch the background hold-sweeper.
  * Expose health/readiness endpoints for nginx and orchestrators.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .core.logging import configure_logging
from .database import Base, SessionLocal, engine
from .redis_client import redis_client
from .routers import auth, bookings, events, holds, organizer, pages, tickets, waitroom, webhooks, ws
from .services.booking_service import release_expired_holds
from .services.realtime import start_seat_broker
from .services.waitroom import admit_step

configure_logging(settings.log_format)
logger = logging.getLogger("ticketflow")
access_logger = logging.getLogger("ticketflow.access")

_SWEEP_INTERVAL_SECONDS = 15


async def _hold_sweeper() -> None:
    """Periodically free seats whose holds have expired."""
    while True:
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
        try:
            db = SessionLocal()
            try:
                freed = await asyncio.to_thread(release_expired_holds, db)
                if freed:
                    logger.info("hold-sweeper released %d expired seat hold(s)", freed)
            finally:
                db.close()
        except Exception:  # never let the background task die silently
            logger.exception("hold-sweeper iteration failed")


async def _waitroom_admitter() -> None:
    """Promote queued users into active sessions at a fixed rate. Safe to run on
    every instance — admission is guarded by a per-event Redis lock + atomic
    ZPOPMIN, so N admitters never exceed the threshold (see docs/HLD.md)."""
    while True:
        await asyncio.sleep(settings.waitroom_admit_interval_seconds)
        if not settings.waitroom_enabled:
            continue
        try:
            admitted = await asyncio.to_thread(admit_step)
            if admitted:
                logger.info("waitroom admitted %d user(s)", admitted)
        except Exception:
            logger.exception("waitroom admitter iteration failed")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # In development we auto-create tables for convenience. In production the
    # schema is owned by Alembic migrations (`alembic upgrade head`, run by the
    # container entrypoint) — so we never silently diverge from the migration history.
    if settings.environment != "production":
        Base.metadata.create_all(bind=engine)
    start_seat_broker(asyncio.get_running_loop())  # daemon thread (see realtime.py)
    tasks = [
        asyncio.create_task(_hold_sweeper()),
        asyncio.create_task(_waitroom_admitter()),
    ]
    logger.info("TicketFlow started (env=%s)", settings.environment)
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t


app = FastAPI(
    title="TicketFlow",
    version="1.0.0",
    summary="Concurrent event-ticket booking system with two-layer double-booking protection.",
    lifespan=lifespan,
    root_path=settings.root_path,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """One structured log line per request, tagged with a request id (taken
    from an incoming X-Request-ID or generated) that is echoed back in the
    response so a client-side error can be matched to its server log line."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    fields = {"request_id": request_id, "method": request.method, "path": request.url.path}
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        access_logger.exception("request failed", extra=fields)
        raise
    response.headers["X-Request-ID"] = request_id
    access_logger.info("request", extra={**fields, "status": response.status_code,
                                         "duration_ms": round((time.perf_counter() - start) * 1000, 1)})
    return response

app.include_router(auth.router)
app.include_router(events.router)
app.include_router(waitroom.router)
app.include_router(holds.router)
app.include_router(bookings.router)
app.include_router(tickets.router)
app.include_router(organizer.router)
app.include_router(webhooks.router)
app.include_router(ws.router)
app.include_router(pages.router)  # public share pages: /e/{id}, /og/*, /sitemap.xml, /robots.txt


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Liveness probe — process is up."""
    return {"status": "ok"}


@app.get("/ready", tags=["meta"])
def ready() -> dict:
    """Readiness probe — dependencies (DB + Redis) are reachable."""
    checks = {"database": False, "redis": False}
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        checks["database"] = True
    except Exception:
        logger.warning("readiness: database unreachable")
    try:
        redis_client.ping()
        checks["redis"] = True
    except Exception:
        logger.warning("readiness: redis unreachable")
    status_ok = all(checks.values())
    return {"status": "ready" if status_ok else "degraded", "checks": checks}
