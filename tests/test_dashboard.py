"""Tests for the Phase 6 dashboard views (app/routers/dashboard.py).

WHAT: drives the real templates through `TestClient`, using the same
logged-in-session pattern as tests/test_races_router.py. Checks the
observable HTML contract (status code, key content present/absent) rather
than exact markup, since template wording is expected to change.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app.models.activity import Activity
from app.models.evaluation import EvalMetric, EvalRun
from app.models.prediction import ModelVersion, Prediction
from app.models.race import RaceClassification, RaceDetail
from app.models.user import User

FAKE_ATHLETE = {"id": 77777, "firstname": "Sam", "lastname": "Lee"}


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


def test_index_shows_login_page_when_logged_out(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Connect with Strava" in response.text


def test_index_shows_status_page_when_logged_in(client) -> None:
    _login(client)

    response = client.get("/")

    assert response.status_code == 200
    assert "Connected as" in response.text
    assert str(FAKE_ATHLETE["id"]) in response.text


def test_races_page_requires_login(client) -> None:
    response = client.get("/dashboard/races")

    assert response.status_code == 401


def test_races_page_lists_effectively_classified_races_with_predictions(client, db_session) -> None:
    _login(client)
    user = db_session.query(User).filter_by(strava_athlete_id=FAKE_ATHLETE["id"]).one()

    activity = Activity(
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
    db_session.add(activity)
    db_session.commit()
    db_session.add(
        RaceClassification(
            activity_id=activity.id, heuristic_is_race=True, distance_category="70.3"
        )
    )
    db_session.add(RaceDetail(activity_id=activity.id, finish_time_s=19_800))
    db_session.commit()

    model_version = ModelVersion(
        algorithm="gradient_boosting",
        training_athlete_ids=[],
        artifact_path="unused.joblib",
        feature_schema_version="v1",
    )
    db_session.add(model_version)
    db_session.commit()
    db_session.add(
        Prediction(
            activity_id=activity.id,
            method="trained_model",
            predicted_finish_time_s=20_000.0,
            model_version_id=model_version.id,
        )
    )
    db_session.commit()

    response = client.get("/dashboard/races")

    assert response.status_code == 200
    assert "IRONMAN 70.3 Austin" in response.text
    assert "70.3" in response.text
    assert "Unmark as race" in response.text


def test_unmark_removes_the_race_from_the_list(client, db_session) -> None:
    _login(client)
    user = db_session.query(User).filter_by(strava_athlete_id=FAKE_ATHLETE["id"]).one()

    activity = Activity(
        user_id=user.id,
        strava_activity_id=2,
        name="Suspicious training run",
        sport_type="Run",
        distance_m=10_000.0,
        moving_time_s=2_000,
        elapsed_time_s=2_050,
        start_date=datetime.now(UTC),
        raw_payload={},
    )
    db_session.add(activity)
    db_session.commit()
    classification = RaceClassification(activity_id=activity.id, heuristic_is_race=True)
    db_session.add(classification)
    db_session.commit()

    response = client.post(f"/dashboard/races/{activity.id}/unmark")

    assert response.status_code == 200
    assert response.text == ""
    db_session.refresh(classification)
    assert classification.manual_override is False
    assert classification.is_race_effective is False

    races_response = client.get("/dashboard/races")
    assert "Suspicious training run" not in races_response.text


def test_unmark_rejects_another_users_activity(client, db_session) -> None:
    _login(client)
    other_user = User(strava_athlete_id=88888)
    db_session.add(other_user)
    db_session.commit()
    other_activity = Activity(
        user_id=other_user.id,
        strava_activity_id=3,
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
    db_session.add(RaceClassification(activity_id=other_activity.id, heuristic_is_race=True))
    db_session.commit()

    response = client.post(f"/dashboard/races/{other_activity.id}/unmark")

    assert response.status_code == 404


def test_scoreboard_shows_placeholder_with_no_eval_run(client) -> None:
    response = client.get("/scoreboard")

    assert response.status_code == 200
    assert "No evaluation report" in response.text


def test_scoreboard_is_public_and_shows_latest_eval_run(client, db_session) -> None:
    user = User(strava_athlete_id=99999)
    db_session.add(user)
    db_session.commit()
    model_version = ModelVersion(
        algorithm="gradient_boosting",
        training_athlete_ids=[],
        artifact_path="unused.joblib",
        feature_schema_version="v1",
    )
    db_session.add(model_version)
    db_session.commit()
    eval_run = EvalRun(
        model_version_id=model_version.id, split_seed=42, n_races_total=3, n_athletes_test=1
    )
    db_session.add(eval_run)
    db_session.commit()
    db_session.add(
        EvalMetric(
            eval_run_id=eval_run.id,
            method="riegel",
            distance_category=None,
            n_races=3,
            mae_minutes=2.5,
            rmse_minutes=3.1,
            mae_pct=4.2,
            rmse_pct=5.0,
        )
    )
    db_session.commit()

    response = client.get("/scoreboard")

    assert response.status_code == 200
    assert "riegel" in response.text
    assert "small N" in response.text
