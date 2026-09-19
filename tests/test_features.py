"""Tests for ml/features.py against the in-memory test DB.

WHAT: seeds real Activity/RaceClassification/TrainingLoadFeatures/RaceDetail
rows and checks `build_feature_matrix`'s join/exclusion/column contract
directly, since that contract (which races count as "usable training data")
is exactly what ml/train.py and, later, evaluation/report.py depend on.
"""

from datetime import UTC, datetime

from app.models.activity import Activity
from app.models.features import TrainingLoadFeatures
from app.models.race import RaceClassification, RaceDetail
from app.models.user import User
from ml.features import FEATURE_COLUMNS, build_feature_matrix

RACE_DATE = datetime(2026, 3, 1, tzinfo=UTC)


def _seed_activity(db_session, user, strava_activity_id: int) -> Activity:
    activity = Activity(
        user_id=user.id,
        strava_activity_id=strava_activity_id,
        name="IRONMAN 70.3",
        sport_type="Run",
        distance_m=21_097.0,
        moving_time_s=5_400,
        elapsed_time_s=5_500,
        start_date=RACE_DATE,
        raw_payload={},
    )
    db_session.add(activity)
    db_session.commit()
    return activity


def test_race_with_full_pipeline_output_appears_with_all_columns(db_session) -> None:
    user = User(strava_athlete_id=1)
    db_session.add(user)
    db_session.commit()
    activity = _seed_activity(db_session, user, 1)
    db_session.add(
        RaceClassification(
            activity_id=activity.id, heuristic_is_race=True, distance_category="70.3"
        )
    )
    db_session.add(RaceDetail(activity_id=activity.id, finish_time_s=19_800))
    db_session.add(
        TrainingLoadFeatures(
            activity_id=activity.id,
            rolling_weekly_mileage_m=30_000.0,
            rolling_weekly_duration_s=10_000.0,
            long_run_distance_4wk_m=15_000.0,
            days_since_last_hard_effort=10,
            taper_indicator=True,
            avg_hr_available=True,
            avg_power_available=False,
            feature_window_days=28,
        )
    )
    db_session.commit()

    df = build_feature_matrix(db_session)

    assert len(df) == 1
    row = df.iloc[0]
    assert row["activity_id"] == str(activity.id)
    assert row["target_distance_m"] == 21_097.0
    assert row["distance_category"] == "70.3"
    assert row["finish_time_s"] == 19_800
    assert bool(row["avg_hr_available"]) is True
    assert set(FEATURE_COLUMNS) <= set(df.columns)


def test_race_without_computed_features_is_excluded(db_session) -> None:
    user = User(strava_athlete_id=2)
    db_session.add(user)
    db_session.commit()
    activity = _seed_activity(db_session, user, 1)
    db_session.add(RaceClassification(activity_id=activity.id, heuristic_is_race=True))
    db_session.add(RaceDetail(activity_id=activity.id, finish_time_s=19_800))
    db_session.commit()
    # No TrainingLoadFeatures row -- compute_features.py hasn't run for this race.

    df = build_feature_matrix(db_session)

    assert len(df) == 0


def test_race_without_a_known_finish_time_is_excluded(db_session) -> None:
    user = User(strava_athlete_id=3)
    db_session.add(user)
    db_session.commit()
    activity = _seed_activity(db_session, user, 1)
    db_session.add(RaceClassification(activity_id=activity.id, heuristic_is_race=True))
    db_session.add(RaceDetail(activity_id=activity.id, finish_time_s=None))
    db_session.add(
        TrainingLoadFeatures(
            activity_id=activity.id,
            avg_hr_available=False,
            avg_power_available=False,
            feature_window_days=28,
        )
    )
    db_session.commit()

    df = build_feature_matrix(db_session)

    assert len(df) == 0


def test_athlete_ids_filter_restricts_the_result(db_session) -> None:
    user_a = User(strava_athlete_id=4)
    user_b = User(strava_athlete_id=5)
    db_session.add_all([user_a, user_b])
    db_session.commit()
    for user, strava_id in [(user_a, 1), (user_b, 2)]:
        activity = _seed_activity(db_session, user, strava_id)
        db_session.add(RaceClassification(activity_id=activity.id, heuristic_is_race=True))
        db_session.add(RaceDetail(activity_id=activity.id, finish_time_s=19_800))
        db_session.add(
            TrainingLoadFeatures(
                activity_id=activity.id,
                avg_hr_available=False,
                avg_power_available=False,
                feature_window_days=28,
            )
        )
    db_session.commit()

    df = build_feature_matrix(db_session, athlete_ids=[user_a.id])

    assert len(df) == 1
    assert df.iloc[0]["user_id"] == str(user_a.id)
