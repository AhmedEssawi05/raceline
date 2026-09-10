"""OAuth token storage — one encrypted-at-rest row per user.

WHAT: holds a user's current Strava access/refresh tokens as Fernet
ciphertext (see app/security.py), plus their expiry.

WHY this is a separate table from `users` rather than columns on it: any
plain `SELECT * FROM users` (a debugging query, an admin view, a future bug)
never has encrypted secrets riding along with ordinary profile data. It also
makes the "delete my data" cascade obviously complete — deleting `users`
takes this table with it via `ondelete="CASCADE"`.

WHY encrypted, not plaintext (explicit spec requirement): a DB dump or a
stray log line that captures a row here still isn't a usable Strava
credential without the Fernet key.

HOW refresh-before-expiry works: `expires_at` is read by
`app.strava.oauth.get_valid_access_token`, which refreshes ahead of expiry
and overwrites this row — nothing else should read
`access_token_encrypted` directly and assume it's still valid.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, LargeBinary, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.user import User


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    access_token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope: Mapped[str] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="oauth_token")
