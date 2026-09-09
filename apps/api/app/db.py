"""SQLite engine + session plumbing.

The database is the villager's own device. It has to survive being closed mid
write, so WAL journalling and a busy timeout are set on every connection.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


def _make_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        # FastAPI serves requests from a thread pool; SQLite objects would
        # otherwise refuse to cross threads.
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
        future=True,
    )


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection: sqlite3.Connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    # WAL keeps reads working while a write is in flight and survives crashes.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Standalone session for scripts and startup tasks."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Bring the schema up to date. Safe to call repeatedly.

    Creates missing tables, then applies additive column migrations, because
    ``create_all`` never alters a table that already exists.
    """
    from . import models  # noqa: F401  (registers mappers)
    from .migrations import apply_additive_migrations

    models.Base.metadata.create_all(bind=engine)
    apply_additive_migrations(engine)
