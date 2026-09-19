"""Integration tests for ml/train.py against the in-memory test DB.

WHAT: seeds real races with computed features and a known finish time, runs
the real `run()`, and checks all three of Phase 4's demo artifacts: the
`model_versions` row, the joblib file on disk, and the `trained_model`
`predictions` rows. Patches only `ml.train.SessionLocal` (test DB instead of
real Postgres) and that session's `close()` (same pattern as
tests/test_predict_riegel.py) — training itself runs for real.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import joblib
import pytest

from app.models.activity import Activity
from app.models.features import TrainingLoadFeatures
from app.models.prediction import ModelVersion, Prediction
from app.models.race import RaceClassification, RaceDetail
from app.models.user import User
from ml.train import run

RACE_DATE = datetime(2026, 1, 1, tzinfo=UTC)


def _seed_race(db_session, user, *, strava_activity_id, distance_m, finish_time_s, offset_days):
    activity = Activity(
        user_id=user.id,
        strava_activity_id=strava_activity_id,
        name="Race",
        sport_type="Run",
        distance_m=distance_m,
        moving_time_s=int(finish_time_s),
        elapsed_time_s=int(finish_time_s),
        start_date=RACE_DATE + timedelta(days=offset_days),
        raw_payload={},
    )
    db_session.add(activity)
    db_session.commit()
    db_session.add(
        RaceClassification(
            activity_id=activity.id, heuristic_is_race=True, distance_category="other"
        )
    )
    db_session.add(RaceDetail(activity_id=activity.id, finish_time_s=finish_time_s))
    db_session.add(
        TrainingLoadFeatures(
            activity_id=activity.id,
            rolling_weekly_mileage_m=20_000.0,
            rolling_weekly_duration_s=15_000.0,
            long_run_distance_4wk_m=10_000.0,
            days_since_last_hard_effort=7,
            taper_indicator=False,
            avg_hr_available=True,
            avg_power_available=False,
            feature_window_days=28,
        )
    )
    db_session.commit()
    return activity


def _seed_training_set(db_session, athlete_id: int) -> list[Activity]:
    user = User(strava_athlete_id=athlete_id)
    db_session.add(user)
    db_session.commit()
    races = [
        _seed_race(
            db_session, user, strava_activity_id=i, distance_m=5_000.0 * i,
            finish_time_s=1_200.0 * i, offset_days=i * 10,
        )
        for i in range(1, 5)
    ]
    return races


def test_train_persists_model_version_artifact_and_predictions(db_session, tmp_path) -> None:
    races = _seed_training_set(db_session, athlete_id=1)

    with (
        patch("ml.train.SessionLocal", lambda: db_session),
        patch.object(db_session, "close"),
    ):
        model_version_id = run(artifact_dir=tmp_path)

    model_version = db_session.get(ModelVersion, model_version_id)
    assert model_version is not None
    assert model_version.algorithm == "gradient_boosting"
    assert model_version.feature_schema_version == "v1"
    assert len(model_version.training_athlete_ids) == 1

    artifact_path = tmp_path / f"{model_version_id}.joblib"
    assert artifact_path.exists()
    assert model_version.artifact_path == str(artifact_path)
    loaded = joblib.load(artifact_path)
    assert loaded.method_name == "trained_model"

    predictions = db_session.query(Prediction).filter_by(model_version_id=model_version_id).all()
    assert {p.activity_id for p in predictions} == {race.id for race in races}
    assert all(p.method == "trained_model" for p in predictions)
    assert all(p.predicted_finish_time_s is not None for p in predictions)


def test_train_respects_explicit_algorithm_argument(db_session, tmp_path) -> None:
    _seed_training_set(db_session, athlete_id=2)

    with (
        patch("ml.train.SessionLocal", lambda: db_session),
        patch.object(db_session, "close"),
    ):
        model_version_id = run(algorithm="gradient_boosting", artifact_dir=tmp_path)

    model_version = db_session.get(ModelVersion, model_version_id)
    assert model_version.algorithm == "gradient_boosting"


def test_train_raises_with_no_usable_training_data(db_session, tmp_path) -> None:
    with (
        patch("ml.train.SessionLocal", lambda: db_session),
        patch.object(db_session, "close"),
    ):
        with pytest.raises(RuntimeError):
            run(artifact_dir=tmp_path)


def test_athlete_ids_filters_which_races_are_trained_on(db_session, tmp_path) -> None:
    races_a = _seed_training_set(db_session, athlete_id=3)
    _seed_training_set(db_session, athlete_id=4)
    athlete_a_id = races_a[0].user_id

    with (
        patch("ml.train.SessionLocal", lambda: db_session),
        patch.object(db_session, "close"),
    ):
        model_version_id = run(athlete_ids=[athlete_a_id], artifact_dir=tmp_path)

    model_version = db_session.get(ModelVersion, model_version_id)
    assert model_version.training_athlete_ids == [str(athlete_a_id)]

    predictions = db_session.query(Prediction).filter_by(model_version_id=model_version_id).all()
    assert {p.activity_id for p in predictions} == {race.id for race in races_a}
