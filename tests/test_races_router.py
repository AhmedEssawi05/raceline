"""Tests for the races router: backfill trigger/status, race listing, and
the manual-override toggle.

WHAT: exercises the router against the real DB layer (repositories, models,
the `is_race_effective` generated column) via TestClient, using the same
logged-in-session pattern as tests/test_auth_flow.py. The only thing mocked
beyond Strava OAuth's token exchange is `worker.queue.queue.enqueue` — there
is no live Redis in this test environment, and the point of these tests is
the router/repository/model layer, not RQ itself.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app.models.activity import Activity
from app.models.race import RaceClassification
from app.models.user import User

FAKE_ATHLETE = {"id": 54321, "firstname": "Alex", "lastname": "Kim"}


def _fake_token_response() -> dict:
    return {
        "access_token": "fake-access-token",
        "refresh_token": "fake-refresh-token",
        "expires_at": int((datetime.now(UTC) + timedelta(hours=6)).timestamp()),
        "athlete": FAKE_ATHLETE,
    }


def _login(client) -> None:
    login_response = client.get("/auth/strava/login", follow_redirects=False)
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]
    with patch("app.strava.oauth.exchange_code_for_token", return_value=_fake_token_response()):
        client.get(
            "/auth/strava/callback",
            params={"code": "fake-code", "state": state},
            follow_redirects=False,
        )


def test_backfill_status_404s_before_any_backfill_has_run(client) -> None:
    _login(client)

    response = client.get("/races/backfill/status")

    assert response.status_code == 404


def test_starting_a_backfill_enqueues_and_returns_queued_status(client) -> None:
    _login(client)

    with patch(
        "worker.queue.queue.enqueue", return_value=SimpleNamespace(id="fake-rq-job-id")
    ) as mock_enqueue:
        response = client.post("/races/backfill")

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    mock_enqueue.assert_called_once()

    status_response = client.get("/races/backfill/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "queued"


def test_list_races_only_returns_effectively_classified_races(client, db_session) -> None:
    _login(client)
    user = db_session.query(User).filter_by(strava_athlete_id=FAKE_ATHLETE["id"]).one()

    race = Activity(
        user_id=user.id,
        strava_activity_id=1,
        name="IRONMAN 70.3 Austin",
        sport_type="Run",
        distance_m=21_097.0,
        moving_time_s=5_400,
        elapsed_time_s=5_500,
        start_date=datetime.now(UTC),
        raw_payload={},
    )
    training_run = Activity(
        user_id=user.id,
        strava_activity_id=2,
        name="Easy shakeout run",
        sport_type="Run",
        distance_m=5_000.0,
        moving_time_s=1_500,
        elapsed_time_s=1_550,
        start_date=datetime.now(UTC),
        raw_payload={},
    )
    db_session.add_all([race, training_run])
    db_session.commit()
    db_session.add_all(
        [
            RaceClassification(
                activity_id=race.id,
                heuristic_is_race=True,
                heuristic_matched_pattern="70.3",
                distance_category="70.3",
            ),
            RaceClassification(activity_id=training_run.id, heuristic_is_race=False),
        ]
    )
    db_session.commit()

    response = client.get("/races")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["activity_id"] == str(race.id)
    assert body[0]["heuristic_is_race"] is True


def test_manual_override_flips_is_race_effective(client, db_session) -> None:
    _login(client)
    user = db_session.query(User).filter_by(strava_athlete_id=FAKE_ATHLETE["id"]).one()

    activity = Activity(
        user_id=user.id,
        strava_activity_id=3,
        name="Suspiciously fast training run",
        sport_type="Run",
        distance_m=10_000.0,
        moving_time_s=2_000,
        elapsed_time_s=2_050,
        start_date=datetime.now(UTC),
        raw_payload={},
    )
    db_session.add(activity)
    db_session.commit()
    classification = RaceClassification(activity_id=activity.id, heuristic_is_race=False)
    db_session.add(classification)
    db_session.commit()

    response = client.post(f"/races/{activity.id}/override", json={"is_race": True})

    assert response.status_code == 200
    assert response.json()["is_race_effective"] is True
    assert classification.manual_override is True

    races_response = client.get("/races")
    assert len(races_response.json()) == 1


def test_override_rejects_an_activity_belonging_to_another_user(client, db_session) -> None:
    _login(client)
    other_user = User(strava_athlete_id=99999)
    db_session.add(other_user)
    db_session.commit()
    other_activity = Activity(
        user_id=other_user.id,
        strava_activity_id=4,
        name="Someone else's race",
        sport_type="Run",
        distance_m=10_000.0,
        moving_time_s=2_000,
        elapsed_time_s=2_050,
        start_date=datetime.now(UTC),
        raw_payload={},
    )
    db_session.add(other_activity)
    db_session.commit()
    db_session.add(RaceClassification(activity_id=other_activity.id, heuristic_is_race=False))
    db_session.commit()

    response = client.post(f"/races/{other_activity.id}/override", json={"is_race": True})

    assert response.status_code == 404
