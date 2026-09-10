"""Pytest fixtures shared across the test suite.

WHAT: (1) enough environment setup so `app.config.get_settings()` and
`app.main.create_app()` don't blow up on import when tests run outside
Docker Compose — no `.env` file, no real Postgres/Redis/Strava app reachable
at all; (2) a `client` fixture that gives auth tests a fully isolated,
in-memory database per test instead of a shared/real Postgres.

WHY module-level `os.environ.setdefault` calls, not a fixture: pydantic-
settings and `app.main`'s session-secret check both run at import time
(`from app.main import app`), which happens before any fixture would run.
`setdefault` means a real `.env`/exported env var (e.g. in CI wired to an
actual Strava test app) always wins over these placeholders.

WHY SQLite in-memory for `db_session`, when the real app runs on Postgres:
the models use SQLAlchemy's dialect-agnostic types (`Uuid`, `DateTime`,
`LargeBinary`) specifically so this works — see app/models/user.py. This
keeps the suite fast and hermetic (no live DB needed to run `pytest`); the
Alembic migration against real Postgres is the actual proof the schema is
correct, not this fixture.
"""

import os

from cryptography.fernet import Fernet

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://raceline:raceline@localhost:5432/raceline"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SESSION_SECRET_KEY", "test-session-secret-not-for-real-use")
os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("STRAVA_CLIENT_ID", "test-client-id")
os.environ.setdefault("STRAVA_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("STRAVA_REDIRECT_URI", "http://localhost:8000/auth/strava/callback")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402, F401 - registers models on Base.metadata
from app.db import Base, get_db  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402


@pytest.fixture()
def db_session():
    """A fresh in-memory SQLite DB, schema created, per test function."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    """A TestClient whose `get_db` dependency is overridden to use the
    isolated `db_session` above, instead of the real Postgres engine.
    """

    def _get_db_override():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = _get_db_override
    with TestClient(fastapi_app) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.clear()
