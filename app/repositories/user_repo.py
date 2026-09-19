"""All DB access for the User/OAuthToken aggregate.

WHAT: every read or write against `users`/`oauth_tokens` goes through one of
these functions — routers and app/strava/oauth.py never build their own
queries against these tables.

WHY this matters for this project specifically: DESIGN.md's data-isolation
requirement ("never expose one user's data to another") is only as solid as
"every query is scoped by the right user." Funneling access through a small,
reviewable set of functions that each take an explicit `User`/`user_id` is
what makes that auditable — a route can't accidentally write an unscoped
query, because there's no ORM session for tables to query against outside
this module.

HOW encryption fits in: `upsert_oauth_token` takes plaintext tokens and
encrypts them (via app.security) before they ever touch the session — no
caller of this module should encrypt/decrypt itself.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.oauth_token import OAuthToken
from app.models.user import User
from app.security import encrypt


def get_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def get_by_strava_athlete_id(db: Session, strava_athlete_id: int) -> User | None:
    return db.scalar(select(User).where(User.strava_athlete_id == strava_athlete_id))


def list_active(db: Session) -> list[User]:
    """Users who haven't disconnected — the population
    `ml/predict_riegel.py` (and later, training/evaluation) iterates over.
    A disconnected user's already-ingested races are kept (see `disconnect`
    below) but shouldn't have new predictions generated for them.
    """
    return list(db.scalars(select(User).where(User.disconnected_at.is_(None))))


def create_user(
    db: Session, *, strava_athlete_id: int, firstname: str | None, lastname: str | None
) -> User:
    user = User(strava_athlete_id=strava_athlete_id, firstname=firstname, lastname=lastname)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def reconnect(db: Session, user: User) -> None:
    """Clear a prior disconnect on a user who is completing OAuth again."""
    user.disconnected_at = None
    db.commit()


def get_oauth_token(db: Session, user: User) -> OAuthToken | None:
    return db.scalar(select(OAuthToken).where(OAuthToken.user_id == user.id))


def upsert_oauth_token(
    db: Session,
    *,
    user: User,
    access_token: str,
    refresh_token: str,
    expires_at: int,
    scope: str,
) -> OAuthToken:
    """Store a (re)issued token pair. `expires_at` is a Unix epoch second
    count, as Strava's token responses return it — converted to a timezone-
    aware datetime here so every other reader gets a real datetime.
    """
    expires_at_dt = datetime.fromtimestamp(expires_at, tz=UTC)
    token = get_oauth_token(db, user)
    if token is None:
        token = OAuthToken(
            user_id=user.id,
            access_token_encrypted=encrypt(access_token),
            refresh_token_encrypted=encrypt(refresh_token),
            expires_at=expires_at_dt,
            scope=scope,
        )
        db.add(token)
    else:
        token.access_token_encrypted = encrypt(access_token)
        token.refresh_token_encrypted = encrypt(refresh_token)
        token.expires_at = expires_at_dt
        token.scope = scope
    db.commit()
    db.refresh(token)
    return token


def disconnect(db: Session, user: User) -> None:
    """Revoke local token storage and mark the user disconnected, without
    deleting their row/history — distinct from `hard_delete` below. See
    app/models/user.py for why these are separate operations.
    """
    token = get_oauth_token(db, user)
    if token is not None:
        db.delete(token)
    user.disconnected_at = datetime.now(UTC)
    db.commit()


def hard_delete(db: Session, user: User) -> None:
    """The actual "delete all my data" action — cascades via FK ondelete."""
    db.delete(user)
    db.commit()
