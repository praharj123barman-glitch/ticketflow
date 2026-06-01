"""SQLAlchemy engine + session factory.

A connection pool is configured explicitly because the whole point of this
project is concurrent access: under load we want a healthy number of pooled
connections rather than opening a fresh TCP/auth handshake per request.
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

# Pool sizing is PER WORKER. With N gunicorn workers the cluster can open up to
# N * (pool_size + max_overflow) connections, so the defaults are kept modest
# (10 + 10 = 20/worker -> 80 for 4 workers, safely under Postgres' default
# max_connections of 100). Override via env on bigger DBs.
engine = create_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,  # transparently recover from dropped connections
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
