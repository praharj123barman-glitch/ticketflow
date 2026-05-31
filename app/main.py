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
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Base, SessionLocal, engine
from .redis_client import redis_client
from .routers import auth, bookings, events
from .services.booking_service import release_expired_holds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("ticketflow")

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


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)  # dev convenience; prod uses Alembic (see docs)
    sweeper = asyncio.create_task(_hold_sweeper())
    logger.info("TicketFlow started (env=%s)", settings.environment)
    try:
        yield
    finally:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper


app = FastAPI(
    title="TicketFlow",
    version="1.0.0",
    summary="Concurrent event-ticket booking system with two-layer double-booking protection.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(events.router)
app.include_router(bookings.router)


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
