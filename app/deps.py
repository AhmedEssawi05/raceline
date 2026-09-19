"""Shared FastAPI dependencies.

WHAT: `get_current_user` turns the signed session cookie (set by
app/routers/auth.py on successful OAuth callback) into a `User` row.
`get_current_user_optional` is the same lookup but returns `None` instead
of 401ing — for the Phase 6 dashboard's `GET /`, which needs to render
*either* the login page or the status page depending on session state,
rather than treating "not logged in" as an error.

WHY it reads `user_id` from `request.session`, never from a URL/body
parameter: a route like `/users/{user_id}/races` would let any logged-in
caller substitute someone else's id and read their data — the data-
isolation requirement in DESIGN.md means the identity a route acts on must
come only from the caller's own verified session cookie, never from
client-supplied input. Every later route that needs "the current user"
should depend on this, not accept a user id argument.
"""

import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.user import User
from app.repositories import user_repo


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    raw_user_id = request.session.get("user_id")
    if raw_user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")

    user = user_repo.get_by_id(db, uuid.UUID(raw_user_id))
    if user is None:
        # Session cookie outlived the user row (e.g. they deleted their
        # data from another tab/session) — clear it so the browser stops
        # sending a cookie that will only ever 401.
        request.session.clear()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Session refers to a user that no longer exists"
        )
    return user


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    raw_user_id = request.session.get("user_id")
    if raw_user_id is None:
        return None
    return user_repo.get_by_id(db, uuid.UUID(raw_user_id))
