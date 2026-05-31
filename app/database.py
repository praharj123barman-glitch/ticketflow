"""SQLAlchemy engine + session factory.

A connection pool is configured explicitly because the whole point of this
project is concurrent access: under load we want a healthy number of pooled
connections rather than opening a fresh TCP/auth handshake per request.
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(
    settings.database_url,
    pool_size=20,        # steady-state pooled connections
    max_overflow=10,     # burst capacity under load
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
