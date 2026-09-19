"""Strava activities API client — the two read endpoints Phase 2 ingestion
needs.

WHAT: `list_activities` wraps the paginated `GET /athlete/activities`
summary list (used by the bulk backfill); `get_activity_detail` wraps
`GET /activities/{id}` (full detail including laps/splits, used only by the
lazy per-race detail fetch).

WHY this is separate from app/strava/oauth.py: oauth.py owns the
token-lifecycle concern (exchange/refresh/revoke); this module owns data
fetching once a valid token already exists. Every function here takes an
already-valid `access_token` — callers get one via
`app.strava.oauth.get_valid_access_token` first, never by reading
`oauth_tokens` directly.

HOW rate limiting is handled: every request here goes through
`rate_limit.call_with_backoff` — see that module for why the budget is
tracked app-wide, not per-athlete.
"""

import httpx

from app.strava.rate_limit import call_with_backoff

ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
ACTIVITY_DETAIL_URL = "https://www.strava.com/api/v3/activities/{id}"


def list_activities(access_token: str, *, page: int, per_page: int = 100) -> list[dict]:
    def _do_request() -> httpx.Response:
        return httpx.get(
            ACTIVITIES_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"page": page, "per_page": per_page},
            timeout=15,
        )

    response = call_with_backoff(_do_request)
    response.raise_for_status()
    return response.json()


def get_activity_detail(access_token: str, strava_activity_id: int) -> dict:
    def _do_request() -> httpx.Response:
        return httpx.get(
            ACTIVITY_DETAIL_URL.format(id=strava_activity_id),
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )

    response = call_with_backoff(_do_request)
    response.raise_for_status()
    return response.json()
