"""Integration test for evaluation/report.py against the in-memory test DB.

WHAT: seeds several athletes' races (with computed features and known
finish times), runs the real `run_report()`, and checks the records
DESIGN.md's Phase 5 demo criterion cares about: a reproducible `eval_runs`
row, `athlete_splits` matching the deterministic split, and `eval_metrics`
rows for all three methods (including `strava_estimate`'s explicit
"unavailable" row). Patches only the `SessionLocal` each orchestrated
module (`ml.train`, `ml.predict_riegel`, `ml.predict_trained_model`,
`evaluation.report`) uses internally — swapped to the shared test session,
same pattern as tests/test_train.py — plus that session's `close()`;
training, prediction, and metric computation all run for real.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.models.activity import Activity
from app.models.evaluation import AthleteSplit, EvalMetric, EvalRun
from app.models.features import TrainingLoadFeatures
from app.models.race import RaceClassification, RaceDetail
from app.models.user import User
from evaluation.report import METHODS, run_report
from evaluation.split import assign_splits

SEED = 42
RACE_DATE = datetime(2026, 1, 1, tzinfo=UTC)

_PATCHES = (
    "evaluation.report.SessionLocal",
    "ml.train.SessionLocal",
    "ml.predict_riegel.SessionLocal",
    "ml.predict_trained_model.SessionLocal",
)


def _run_report_against(db_session, tmp_path, seed=SEED):
    with (
        patch(_PATCHES[0], lambda: db_session),
        patch(_PATCHES[1], lambda: db_session),
        patch(_PATCHES[2], lambda: db_session),
        patch(_PATCHES[3], lambda: db_session),
        patch.object(db_session, "close"),
    ):
        return run_report(seed=seed, artifact_dir=tmp_path)


def _seed_race(
    db_session,
    user,
    *,
    strava_activity_id,
    distance_m,
    finish_time_s,
    offset_days,
    distance_category,
):
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
            activity_id=activity.id, heuristic_is_race=True, distance_category=distance_category
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


def _seed_athlete(db_session, strava_athlete_id, distance_category):
    user = User(strava_athlete_id=strava_athlete_id)
    db_session.add(user)
    db_session.commit()
    for i in range(1, 4):
        _seed_race(
            db_session,
            user,
            strava_activity_id=i,
            distance_m=5_000.0 * i,
            finish_time_s=1_200.0 * i,
            offset_days=i * 10,
            distance_category=distance_category,
        )
    return user


def test_run_report_produces_a_reproducible_eval_run_and_metrics(db_session, tmp_path) -> None:
    users = [
        _seed_athlete(db_session, strava_athlete_id=i, distance_category=category)
        for i, category in enumerate(["sprint", "sprint", "olympic", "olympic"], start=1)
    ]
    user_ids = [u.id for u in users]

    eval_run_id = _run_report_against(db_session, tmp_path)

    eval_run = db_session.get(EvalRun, eval_run_id)
    assert eval_run is not None
    assert eval_run.split_seed == SEED

    expected_split = assign_splits(user_ids, seed=SEED)
    expected_test_ids = {uid for uid, s in expected_split.items() if s == "test"}
    assert eval_run.n_athletes_test == len(expected_test_ids)

    splits = db_session.query(AthleteSplit).filter_by(eval_run_id=eval_run_id).all()
    assert {(s.user_id, s.split) for s in splits} == set(expected_split.items())

    metrics = db_session.query(EvalMetric).filter_by(eval_run_id=eval_run_id).all()
    assert {m.method for m in metrics} == set(METHODS)

    combined_rows = {m.method: m for m in metrics if m.distance_category is None}
    assert set(combined_rows) == set(METHODS)

    # strava_estimate is always explicitly unavailable, never fabricated.
    assert combined_rows["strava_estimate"].n_races == 0
    assert combined_rows["strava_estimate"].mae_minutes is None


def test_run_report_is_reproducible_given_the_same_seed(db_session, tmp_path) -> None:
    for i, category in enumerate(["sprint", "olympic"], start=1):
        _seed_athlete(db_session, strava_athlete_id=i, distance_category=category)

    first_run_id = _run_report_against(db_session, tmp_path)
    second_run_id = _run_report_against(db_session, tmp_path)

    first_splits = db_session.query(AthleteSplit).filter_by(eval_run_id=first_run_id)
    second_splits = db_session.query(AthleteSplit).filter_by(eval_run_id=second_run_id)
    first_split = {s.user_id: s.split for s in first_splits}
    second_split = {s.user_id: s.split for s in second_splits}
    assert first_split == second_split
