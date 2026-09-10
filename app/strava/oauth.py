"""Strava OAuth2 authorization-code flow.

WHAT: builds the Strava "authorize" redirect URL, exchanges an
authorization code (or a refresh token) for an access/refresh token pair,
and best-effort revokes a token with Strava on disconnect.

WHY `get_valid_access_token` exists here and is the one function later
phases (Phase 2 ingestion) should call, rather than reading
`oauth_tokens.access_token_encrypted` directly: it's what implements the
spec's "refresh automatically before they expire" requirement — callers get
back a token that's guaranteed usable right now, without needing to know
anything about expiry or the refresh flow themselves.

WHY refresh happens `_REFRESH_BUFFER` early, not exactly at expiry: a token
that expires mid-request (e.g. partway through a paginated Phase 2
backfill) is exactly as useless as one that's already expired. Refreshing
a few minutes ahead of the deadline avoids that race outright.

WHY credential checks are a runtime function (`_require_strava_credentials`)
rather than a required config field: `app/config.py` leaves these optional
so the rest of the app (health check, a not-yet-connected status page) can
run without a registered Strava app; this is the actual point of use, so
it's where "is Strava configured" should be checked, with an error that
says exactly what to do about it.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.user import User
from app.repositories import user_repo
from app.security import decrypt

AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
DEAUTHORIZE_URL = "https://www.strava.com/oauth/deauthorize"

# Read-only scope, per spec — raceline never needs to write to a user's
# Strava account.
SCOPE = "activity:read_all"

_REFRESH_BUFFER = timedelta(minutes=5)


def _require_strava_credentials() -> tuple[str, str, str]:
    settings = get_settings()
    has_all_creds = bool(
        settings.strava_client_id
        and settings.strava_client_secret
        and settings.strava_redirect_uri
    )
    if not has_all_creds:
        raise RuntimeError(
            "STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET / STRAVA_REDIRECT_URI must all be "
            "set to use Strava login. Register an app at "
            "https://www.strava.com/settings/api and fill these into .env."
        )
    return settings.strava_client_id, settings.strava_client_secret, settings.strava_redirect_uri


def build_authorize_url(state: str) -> str:
    client_id, _client_secret, redirect_uri = _require_strava_credentials()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": SCOPE,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_token(code: str) -> dict:
    """Trade a one-time authorization `code` (from the callback query
    string) for a token pair. The response also includes an `athlete`
    summary object — that's how the callback learns who just logged in.
    """
    client_id, client_secret, _redirect_uri = _require_strava_credentials()
    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _refresh(refresh_token: str) -> dict:
    client_id, client_secret, _redirect_uri = _require_strava_credentials()
    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def deauthorize(access_token: str) -> None:
    """Best-effort: ask Strava to revoke this token. Disconnect must
    succeed locally even if this call fails (token already invalid, Strava
    outage) — we stop storing/using the token either way.
    """
    try:
        response = httpx.post(DEAUTHORIZE_URL, data={"access_token": access_token}, timeout=10)
        response.raise_for_status()
    except httpx.HTTPError:
        pass


def get_valid_access_token(db: Session, user: User) -> str:
    token = user_repo.get_oauth_token(db, user)
    if token is None:
        raise RuntimeError(f"User {user.id} has no stored Strava token")

    if datetime.now(UTC) >= token.expires_at - _REFRESH_BUFFER:
        refreshed = _refresh(decrypt(token.refresh_token_encrypted))
        token = user_repo.upsert_oauth_token(
            db,
            user=user,
            access_token=refreshed["access_token"],
            refresh_token=refreshed["refresh_token"],
            expires_at=refreshed["expires_at"],
            scope=SCOPE,
        )

    return decrypt(token.access_token_encrypted)
