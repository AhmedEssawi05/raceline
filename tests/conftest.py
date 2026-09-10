"""Pytest fixtures shared across the test suite.

WHAT (for now): just enough environment setup so `app.config.get_settings()`
doesn't blow up on import when tests run outside Docker Compose (no `.env`
file, no real Postgres/Redis reachable at all).

WHY module-level `os.environ.setdefault` calls, not a fixture: pydantic-
settings reads the environment at import time (`app.db` builds the SQLAlchemy
engine at module import, not lazily), so these must be set before any test
module does `from app.main import app` — a fixture function runs too late.
`setdefault` means a real `.env`/exported env var (e.g. in CI wired to an
actual test DB) always wins over these placeholders.

Phase 1+ will likely add a real test-database fixture (e.g. a transactional
session per test, or testcontainers) here once there are models to persist.
"""

import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://raceline:raceline@localhost:5432/raceline"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
