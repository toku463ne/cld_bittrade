"""SQLAlchemy engine and session management.

All DB access in the codebase goes through :func:`get_session` (per CLAUDE.md:
all DB access via SQLAlchemy ORM). The engine is created lazily from the active
:class:`~src.config.Settings` so that ``.env.dev`` and ``.env.bt`` never mix.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create (once) and return the SQLAlchemy engine for the active env.

    Returns:
        A process-wide cached :class:`~sqlalchemy.Engine`.
    """
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a transactional session, committing on success, rolling back on error.

    Yields:
        An open :class:`~sqlalchemy.orm.Session`.

    Raises:
        Exception: Re-raises any error after rolling back. Errors are never
            suppressed (per coding standards).
    """
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
