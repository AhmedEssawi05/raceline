"""User model — one row per connected Strava athlete.

WHAT: the only identity table in raceline. `strava_athlete_id` is the
natural external key since Strava OAuth is the sole login method (per
spec) — no password, email, or username fields exist here.

WHY `disconnected_at` and `is_deleted` are two different, narrow-purpose
fields rather than one status flag: `disconnected_at` marks a user who
revoked Strava access but whose historical data (once ingestion exists in
Phase 2+) is still kept for the aggregate scoreboard and a possible future
reconnect. `is_deleted` is *not* the mechanism that erases data — the actual
"delete my data" action (app/repositories/user_repo.hard_delete) hard-
deletes this row outright, which cascades through every FK'd table via
`ondelete="CASCADE"` (see OAuthToken.user_id, and later phases' models).
`is_deleted` exists only as a transient flag a future confirmation UI could
set between "user clicked delete" and "cascade actually fires."

Uses SQLAlchemy's dialect-agnostic `Uuid`/`DateTime` types rather than
Postgres-specific ones so the same model works against SQLite in tests
(see tests/conftest.py) without a live Postgres — the Alembic migration is
still what defines the real Postgres column types in production.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.oauth_token import OAuthToken


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    strava_athlete_id: Mapped[int] = mapped_column(unique=True, index=True, nullable=False)
    firstname: Mapped[str | None] = mapped_column(nullable=True)
    lastname: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False)

    oauth_token: Mapped["OAuthToken | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
