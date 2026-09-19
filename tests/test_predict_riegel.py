"""Integration tests for ml/predict_riegel.py against the in-memory test DB.

WHAT: seeds real Activity/RaceClassification/RaceDetail rows and runs the
real `run()` function, patching only `ml.predict_riegel.SessionLocal` (so it
uses the test session instead of a real Postgres connection) and that
session's `close()` (so the job doesn't tear down the fixture out from under
the test — see the same pattern in tests/test_ingestion_error_handling.py).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.models.activity import Activity
from app.models.prediction import Prediction
from app.models.race import RaceClassification, RaceDetail
from app.models.user import User
from ml.predict_riegel import run
from ml.riegel import RIEGEL_EXPONENT

RACE_ONE_DATE = datetime(2026, 1, 1, tzinfo=UTC)
RACE_TWO_DATE = RACE_ONE_DATE + timedelta(days=60)


def _make_race(db_session, user, *, strava_activity_id, start_date, distance_m, finish_time_s):
    activity = Activity(
        user_id=user.id,
        strava_activity_id=strava_activity_id,
        name="Race",
        sport_type="Run",
        distance_m=distance_m,
        moving_time_s=int(finish_time_s),
        elapsed_time_s=int(finish_time_s),
        start_date=start_date,
        raw_payload={},
    )
    db_session.add(activity)
    db_session.commit()
    db_session.add(RaceClassification(activity_id=activity.id, heuristic_is_race=True))
    db_session.add(RaceDetail(activity_id=activity.id, finish_time_s=finish_time_s))
    db_session.commit()
    return activity


def test_first_race_has_no_reference_and_gets_no_prediction(db_session) -> None:
    user = User(strava_athlete_id=1)
    db_session.add(user)
    db_session.commit()
    first = _make_race(
        db_session, user, strava_activity_id=1, start_date=RACE_ONE_DATE,
        distance_m=5_000.0, finish_time_s=1_200,
    )

    with (
        patch("ml.predict_riegel.SessionLocal", lambda: db_session),
        patch.object(db_session, "close"),
    ):
        written = run()

    assert written == 0
    assert db_session.query(Prediction).filter_by(activity_id=first.id).one_or_none() is None


def test_later_race_is_predicted_from_the_immediately_prior_race(db_session) -> None:
    user = User(strava_athlete_id=2)
    db_session.add(user)
    db_session.commit()
    _make_race(
        db_session, user, strava_activity_id=1, start_date=RACE_ONE_DATE,
        distance_m=5_000.0, finish_time_s=1_200.0,
    )
    second = _make_race(
        db_session, user, strava_activity_id=2, start_date=RACE_TWO_DATE,
        distance_m=10_000.0, finish_time_s=2_600.0,
    )

    with (
        patch("ml.predict_riegel.SessionLocal", lambda: db_session),
        patch.object(db_session, "close"),
    ):
        written = run()

    assert written == 1
    prediction = db_session.query(Prediction).filter_by(activity_id=second.id).one()
    assert prediction.method == "riegel"
    expected = 1_200.0 * (10_000.0 / 5_000.0) ** RIEGEL_EXPONENT
    assert prediction.predicted_finish_time_s == expected


def test_rerunning_overwrites_rather_than_duplicates(db_session) -> None:
    user = User(strava_athlete_id=3)
    db_session.add(user)
    db_session.commit()
    _make_race(
        db_session, user, strava_activity_id=1, start_date=RACE_ONE_DATE,
        distance_m=5_000.0, finish_time_s=1_200.0,
    )
    second = _make_race(
        db_session, user, strava_activity_id=2, start_date=RACE_TWO_DATE,
        distance_m=10_000.0, finish_time_s=2_600.0,
    )

    with (
        patch("ml.predict_riegel.SessionLocal", lambda: db_session),
        patch.object(db_session, "close"),
    ):
        run()
        run()

    predictions = db_session.query(Prediction).filter_by(activity_id=second.id).all()
    assert len(predictions) == 1


def test_disconnected_users_are_skipped(db_session) -> None:
    user = User(strava_athlete_id=4, disconnected_at=datetime.now(UTC))
    db_session.add(user)
    db_session.commit()
    _make_race(
        db_session, user, strava_activity_id=1, start_date=RACE_ONE_DATE,
        distance_m=5_000.0, finish_time_s=1_200.0,
    )
    _make_race(
        db_session, user, strava_activity_id=2, start_date=RACE_TWO_DATE,
        distance_m=10_000.0, finish_time_s=2_600.0,
    )

    with (
        patch("ml.predict_riegel.SessionLocal", lambda: db_session),
        patch.object(db_session, "close"),
    ):
        written = run()

    assert written == 0
