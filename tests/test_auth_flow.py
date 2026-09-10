"""End-to-end tests for the Strava OAuth login flow.

WHAT: drives the real router code (login → callback → status → disconnect/
delete) through `TestClient`, mocking only the two functions that would
otherwise make real network calls to Strava
(`app.strava.oauth.exchange_code_for_token` / `.deauthorize`) — everything
else (session handling, DB writes, encryption, the CSRF state check) runs
for real against the in-memory DB from tests/conftest.py.

WHY this can't fully replace manually testing against real Strava: nobody
here has registered a real Strava API application, so the actual
authorize-code exchange has never been exercised against Strava's servers.
This suite proves raceline's side of the contract is correct; the
`STRAVA_CLIENT_ID`/`SECRET` in .env.example are still needed to confirm the
real integration once someone registers an app.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app.models.user import User

FAKE_ATHLETE = {"id": 12345, "firstname": "Jane", "lastname": "Doe"}


def _fake_token_response() -> dict:
    return {
        "access_token": "fake-access-token",
        "refresh_token": "fake-refresh-token",
        "expires_at": int((datetime.now(UTC) + timedelta(hours=6)).timestamp()),
        "athlete": FAKE_ATHLETE,
    }


def _login_and_callback(client) -> None:
    login_response = client.get("/auth/strava/login", follow_redirects=False)
    assert login_response.status_code in (302, 307)
    redirect_qs = parse_qs(urlparse(login_response.headers["location"]).query)
    state = redirect_qs["state"][0]

    with patch("app.strava.oauth.exchange_code_for_token", return_value=_fake_token_response()):
        callback_response = client.get(
            "/auth/strava/callback",
            params={"code": "fake-code", "state": state},
            follow_redirects=False,
        )
    assert callback_response.status_code in (302, 307)
    assert callback_response.headers["location"] == "/auth/status"


def test_login_redirects_to_strava_with_a_state_param(client) -> None:
    response = client.get("/auth/strava/login", follow_redirects=False)

    assert response.status_code in (302, 307)
    location = urlparse(response.headers["location"])
    assert location.netloc == "www.strava.com"
    query = parse_qs(location.query)
    assert query["scope"] == ["activity:read_all"]
    assert "state" in query


def test_callback_rejects_mismatched_state(client) -> None:
    client.get("/auth/strava/login", follow_redirects=False)

    response = client.get(
        "/auth/strava/callback", params={"code": "fake-code", "state": "not-the-real-state"}
    )

    assert response.status_code == 400


def test_status_requires_login(client) -> None:
    response = client.get("/auth/status")

    assert response.status_code == 401


def test_full_login_flow_creates_user_and_reports_status(client, db_session) -> None:
    _login_and_callback(client)

    status_response = client.get("/auth/status")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["connected"] is True
    assert body["strava_athlete_id"] == FAKE_ATHLETE["id"]
    assert body["firstname"] == FAKE_ATHLETE["firstname"]

    user = db_session.query(User).filter_by(strava_athlete_id=FAKE_ATHLETE["id"]).one()
    assert user.oauth_token is not None


def test_disconnect_clears_session_and_removes_token_but_keeps_user(client, db_session) -> None:
    _login_and_callback(client)

    with patch("app.strava.oauth.deauthorize") as mock_deauthorize:
        response = client.post("/auth/disconnect")
    assert response.status_code == 200
    assert response.json() == {"status": "disconnected"}
    mock_deauthorize.assert_called_once()

    # Session was cleared — further requests are logged out.
    assert client.get("/auth/status").status_code == 401

    # But the user row (and history, once ingestion exists) survives.
    user = db_session.query(User).filter_by(strava_athlete_id=FAKE_ATHLETE["id"]).one()
    assert user.disconnected_at is not None
    assert user.oauth_token is None


def test_delete_removes_the_user_row_entirely(client, db_session) -> None:
    _login_and_callback(client)

    with patch("app.strava.oauth.deauthorize"):
        response = client.post("/auth/delete")
    assert response.status_code == 200
    assert response.json() == {"status": "deleted"}

    assert client.get("/auth/status").status_code == 401
    remaining = db_session.query(User).filter_by(strava_athlete_id=FAKE_ATHLETE["id"]).one_or_none()
    assert remaining is None
