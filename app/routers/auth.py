"""Strava OAuth login, account status, disconnect, and delete.

WHAT: `/auth/strava/login` starts the OAuth flow, `/auth/strava/callback`
completes it, `/auth/status` reports the logged-in user's connection state,
and `/auth/disconnect` / `/auth/delete` implement the two distinct privacy
actions from the spec (see app/models/user.py for why they're different).

WHY there's no Jinja2/HTMX dashboard here yet even though DESIGN.md's
Phase 1 demo criterion is "see connected status page": that templating
layer is Phase 6's job. `/auth/status` is a bare JSON endpoint standing in
for it now, the same pattern DESIGN.md used for Phase 2's manual-override
toggle — it proves the underlying flow end-to-end without pulling forward
work that belongs to a later phase.

WHY `state` is stored in the session and checked on callback: it's the
standard OAuth CSRF defense — without it, an attacker could trick a
victim's browser into completing *the attacker's* authorization code
against the victim's session, linking the attacker's Strava account to the
victim's raceline login.
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.repositories import user_repo
from app.schemas.auth import AccountStatus
from app.security import decrypt
from app.strava import oauth as strava_oauth

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/strava/login")
def login(request: Request) -> RedirectResponse:
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    return RedirectResponse(strava_oauth.build_authorize_url(state))


@router.get("/strava/callback")
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if error:
        # The user clicked "Cancel" on Strava's consent screen, or Strava
        # rejected the request — either way, nothing to recover from here.
        raise HTTPException(400, f"Strava authorization was not completed: {error}")

    expected_state = request.session.pop("oauth_state", None)
    if not state or not expected_state or state != expected_state:
        raise HTTPException(400, "Invalid or missing OAuth state — please try logging in again")
    if not code:
        raise HTTPException(400, "Strava did not return an authorization code")

    token_data = strava_oauth.exchange_code_for_token(code)
    athlete = token_data["athlete"]

    user = user_repo.get_by_strava_athlete_id(db, athlete["id"])
    if user is None:
        user = user_repo.create_user(
            db,
            strava_athlete_id=athlete["id"],
            firstname=athlete.get("firstname"),
            lastname=athlete.get("lastname"),
        )
    elif user.disconnected_at is not None:
        user_repo.reconnect(db, user)

    user_repo.upsert_oauth_token(
        db,
        user=user,
        access_token=token_data["access_token"],
        refresh_token=token_data["refresh_token"],
        expires_at=token_data["expires_at"],
        scope=strava_oauth.SCOPE,
    )

    request.session["user_id"] = str(user.id)
    return RedirectResponse("/auth/status")


@router.get("/status", response_model=AccountStatus)
def status(user: User = Depends(get_current_user)) -> AccountStatus:
    return AccountStatus(
        connected=user.disconnected_at is None,
        strava_athlete_id=user.strava_athlete_id,
        firstname=user.firstname,
        lastname=user.lastname,
        connected_since=user.created_at,
    )


@router.post("/disconnect")
def disconnect(
    request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    token = user_repo.get_oauth_token(db, user)
    if token is not None:
        strava_oauth.deauthorize(decrypt(token.access_token_encrypted))
    user_repo.disconnect(db, user)
    request.session.clear()
    return {"status": "disconnected"}


@router.post("/delete")
def delete(
    request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    token = user_repo.get_oauth_token(db, user)
    if token is not None:
        strava_oauth.deauthorize(decrypt(token.access_token_encrypted))
    user_repo.hard_delete(db, user)
    request.session.clear()
    return {"status": "deleted"}
