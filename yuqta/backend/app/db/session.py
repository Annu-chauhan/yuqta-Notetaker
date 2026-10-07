from collections.abc import Iterator
from functools import lru_cache
import logging

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


logger = logging.getLogger(__name__)


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def new_session() -> Session:
    """A session for background work (outside a request); close it, e.g. with `with new_session() as db:`."""
    return _session_factory()()


def get_session_factory():
    """FastAPI dependency for code that opens its own sessions (overridable in tests)."""
    return new_session


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a session and always closes it."""
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()


def check_database() -> bool:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as error:
        logger.warning("Database check failed: %s", error.__class__.__name__)
        return False
