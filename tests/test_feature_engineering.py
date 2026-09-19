"""Tests for ingestion/feature_engineering.py — pure functions, no DB, per
its own docstring. This is the heaviest-coverage test file in Phase 2 (mirrored
after DESIGN.md's stated priority for test_split.py in Phase 5) because
DESIGN.md's explicit-null contract is the thing most likely to be silently
wrong in a rolling-window computation.
"""

from datetime import UTC, datetime, timedelta

from ingestion.feature_engineering import (
    DEFAULT_WINDOW_DAYS,
    PriorActivitySample,
    compute_training_load_features,
)

RACE_DATE = datetime(2026, 6, 1, tzinfo=UTC)


def _sample(
    days_before: int,
    distance_m: float,
    sport_type: str = "Run",
    moving_time_s: int = 1800,
    is_hard_effort: bool = False,
) -> PriorActivitySample:
    return PriorActivitySample(
        start_date=RACE_DATE - timedelta(days=days_before),
        distance_m=distance_m,
        moving_time_s=moving_time_s,
        sport_type=sport_type,
        is_hard_effort=is_hard_effort,
    )


def test_no_prior_history_yields_explicit_nulls_not_zeros() -> None:
    features = compute_training_load_features(
        race_start_date=RACE_DATE,
        race_avg_heart_rate=None,
        race_avg_power_w=None,
        prior_activities=[],
    )

    assert features["rolling_weekly_mileage_m"] is None
    assert features["rolling_weekly_duration_s"] is None
    assert features["long_run_distance_4wk_m"] is None
    assert features["taper_indicator"] is None
    assert features["days_since_last_hard_effort"] is None
    assert features["feature_window_days"] == DEFAULT_WINDOW_DAYS


def test_rolling_weekly_mileage_averages_total_window_distance_per_week() -> None:
    # Four weeks, 10km each -> 40km total over a 28-day window -> 10km/week.
    prior = [_sample(days_before=d, distance_m=10_000.0) for d in (3, 10, 17, 24)]

    features = compute_training_load_features(
        race_start_date=RACE_DATE, race_avg_heart_rate=150.0, race_avg_power_w=None,
        prior_activities=prior,
    )

    assert features["rolling_weekly_mileage_m"] == 10_000.0


def test_activities_outside_the_window_are_excluded() -> None:
    prior = [_sample(days_before=100, distance_m=999_000.0)]

    features = compute_training_load_features(
        race_start_date=RACE_DATE, race_avg_heart_rate=None, race_avg_power_w=None,
        prior_activities=prior,
    )

    assert features["rolling_weekly_mileage_m"] is None


def test_long_run_distance_only_considers_run_sport_types() -> None:
    prior = [
        _sample(days_before=5, distance_m=30_000.0, sport_type="Ride"),
        _sample(days_before=6, distance_m=18_000.0, sport_type="Run"),
    ]

    features = compute_training_load_features(
        race_start_date=RACE_DATE, race_avg_heart_rate=None, race_avg_power_w=None,
        prior_activities=prior,
    )

    assert features["long_run_distance_4wk_m"] == 18_000.0


def test_taper_indicator_true_when_final_week_well_below_baseline() -> None:
    # 3-week baseline at 10km/week, final week at 1km -> well under 50%.
    baseline = [_sample(days_before=d, distance_m=10_000.0) for d in (10, 17, 24)]
    recent = [_sample(days_before=2, distance_m=1_000.0)]

    features = compute_training_load_features(
        race_start_date=RACE_DATE, race_avg_heart_rate=None, race_avg_power_w=None,
        prior_activities=baseline + recent,
    )

    assert features["taper_indicator"] is True


def test_taper_indicator_false_when_final_week_holds_steady() -> None:
    baseline = [_sample(days_before=d, distance_m=10_000.0) for d in (10, 17, 24)]
    recent = [_sample(days_before=2, distance_m=10_000.0)]

    features = compute_training_load_features(
        race_start_date=RACE_DATE, race_avg_heart_rate=None, race_avg_power_w=None,
        prior_activities=baseline + recent,
    )

    assert features["taper_indicator"] is False


def test_taper_indicator_is_null_without_a_baseline_to_compare_against() -> None:
    # Everything falls inside the "recent" 7 days -- nothing to compare to.
    recent_only = [_sample(days_before=2, distance_m=5_000.0)]

    features = compute_training_load_features(
        race_start_date=RACE_DATE, race_avg_heart_rate=None, race_avg_power_w=None,
        prior_activities=recent_only,
    )

    assert features["taper_indicator"] is None


def test_days_since_last_hard_effort_looks_past_the_rolling_window() -> None:
    # 40 days ago is outside the default 28-day window but should still be
    # found -- this feature intentionally isn't capped to the same window.
    prior = [_sample(days_before=40, distance_m=15_000.0, is_hard_effort=True)]

    features = compute_training_load_features(
        race_start_date=RACE_DATE, race_avg_heart_rate=None, race_avg_power_w=None,
        prior_activities=prior,
    )

    assert features["days_since_last_hard_effort"] == 40


def test_days_since_last_hard_effort_uses_the_most_recent_match() -> None:
    prior = [
        _sample(days_before=20, distance_m=15_000.0, is_hard_effort=True),
        _sample(days_before=5, distance_m=12_000.0, is_hard_effort=True),
        _sample(days_before=2, distance_m=5_000.0, is_hard_effort=False),
    ]

    features = compute_training_load_features(
        race_start_date=RACE_DATE, race_avg_heart_rate=None, race_avg_power_w=None,
        prior_activities=prior,
    )

    assert features["days_since_last_hard_effort"] == 5


def test_missing_hr_and_power_are_flagged_not_defaulted() -> None:
    features = compute_training_load_features(
        race_start_date=RACE_DATE, race_avg_heart_rate=None, race_avg_power_w=None,
        prior_activities=[],
    )

    assert features["avg_hr_available"] is False
    assert features["avg_power_available"] is False


def test_present_hr_and_power_are_flagged_available() -> None:
    features = compute_training_load_features(
        race_start_date=RACE_DATE, race_avg_heart_rate=150.0, race_avg_power_w=200.0,
        prior_activities=[],
    )

    assert features["avg_hr_available"] is True
    assert features["avg_power_available"] is True
