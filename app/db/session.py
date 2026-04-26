"""SQLAlchemy engine + session factory.

The engine is lazily constructed so importing this module does not require
a live database (important for tests and CLI scripts that run in mock mode).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = _ensure_ssl(settings.database_url)
        log.info("creating sqlalchemy engine", url=_redact(url))
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


def _ensure_ssl(url: str) -> str:
    # Supabase refuses non-SSL connections; psycopg won't set sslmode on
    # its own. Inject sslmode=require if the user hasn't.
    if "sslmode=" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}sslmode=require"


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )
    return _SessionFactory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context-managed session: commits on success, rolls back on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yields a session, commits, closes."""
    with session_scope() as s:
        yield s


def _redact(url: str) -> str:
    """Hide credentials when logging the connection URL."""
    if "@" not in url:
        return url
    head, tail = url.split("@", 1)
    if "://" in head:
        scheme, creds = head.split("://", 1)
        return f"{scheme}://***@{tail}"
    return f"***@{tail}"
