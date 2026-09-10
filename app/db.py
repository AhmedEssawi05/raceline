"""SQLAlchemy engine, session, and declarative base.

WHAT: The one place that talks to Postgres at the SQLAlchemy layer — the
`engine`, a `SessionLocal` factory, the `Base` class all ORM models will
inherit from, and a `get_db` FastAPI dependency for per-request sessions.

WHY: Sync (not async) SQLAlchemy, per DESIGN.md — simpler at this project's
scale (5-10 users) and lets the RQ worker process import and use the exact
same models/session machinery as the FastAPI app without maintaining a
separate async engine or sync/async model duplication.

`Base` is defined here, not in app/models/, so that both the (currently
empty) `app/models/` package and `migrations/env.py` can import it without a
circular import: models will subclass `Base`, and Alembic's autogenerate
needs `Base.metadata` to diff against. No models exist yet (Phase 0) — this
file just establishes the wiring Phase 1 will hang models onto.

HOW: Routes/repositories depend on `get_db`, e.g.
`def endpoint(db: Session = Depends(get_db))`. Never import `SessionLocal`
and construct a session by hand inside a route — that skips the
try/finally close in `get_db` and can leak connections.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
