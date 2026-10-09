import os

# Tests must never depend on a developer's .env; force the test environment before app import.
os.environ["APP_ENV"] = "test"
os.environ["API_AUTH_TOKEN"] = ""  # auth tests turn it on explicitly
for _provider_key in ("STT_PROVIDER", "LLM_PROVIDER", "GOOGLE_MODE", "MEETING_BOT_PROVIDER"):
    os.environ[_provider_key] = "mock"
# Never let real credentials from .env / the container reach tests (or real APIs).
for _secret in ("DEEPGRAM_API_KEY", "LLM_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "ANTHROPIC_API_KEY",
                "RECALL_API_KEY", "TOKEN_ENCRYPTION_KEY"):
    os.environ[_secret] = ""
os.environ["LLM_MODEL"] = "typesafe/jev-router"
os.environ["DISPLAY_TIMEZONE"] = "UTC"
os.environ["MINUTES_EMAIL"] = "off"
os.environ["GMAIL_SEND"] = "false"
for _reminder_setting in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "REMINDER_TO", "MINUTES_TO", "INTERNAL_DOMAINS"):
    os.environ[_reminder_setting] = ""  # never send real email from tests  # times in tests are asserted in UTC, whatever the developer's .env says

from collections.abc import Iterator  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import models  # noqa: E402,F401
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def memory_db() -> Iterator[sessionmaker[Session]]:
    """Fresh in-memory SQLite schema per test, built from the ORM models."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def api(memory_db: sessionmaker[Session]) -> Iterator[TestClient]:
    def override_db() -> Iterator[Session]:
        session = memory_db()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def seeded_db(memory_db: sessionmaker[Session]) -> sessionmaker[Session]:
    """In-memory schema loaded with data/seed.sql (TRUNCATE is Postgres-only, so it is skipped)."""
    import re
    from pathlib import Path

    from app.core.config import get_settings

    script = Path(get_settings().seed_sql_path).read_text(encoding="utf-8")
    script = re.sub(r"^TRUNCATE[^;]*;", "", script, flags=re.MULTILINE)
    connection = memory_db.kw["bind"].raw_connection()
    try:
        connection.driver_connection.executescript(script)
    finally:
        connection.close()
    return memory_db


@pytest.fixture
def seeded_api(seeded_db: sessionmaker[Session]) -> Iterator[TestClient]:
    def override_db() -> Iterator[Session]:
        session = seeded_db()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
