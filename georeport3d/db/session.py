"""Engine, session, and the transaction boundary repositories run inside.

Repositories never commit. They record intent against a session, and the caller
decides when that work becomes durable. A job controller can therefore write a
cache entry, a usage record, and a job transition in one transaction, so a crash
midway cannot leave spend recorded against a job that never advanced.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_database_engine(url: str, *, echo: bool = False) -> Engine:
    """Build an engine with pre-ping, so a recycled connection fails fast."""
    if not url or not url.strip():
        raise ValueError("database url must be a non-empty string")
    return create_engine(url, echo=echo, pool_pre_ping=True, future=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a session factory that leaves flush timing to the caller."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def unit_of_work(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Run one transaction: commit on success, roll back on any failure."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
