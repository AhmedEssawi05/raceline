"""Tests for ml/gradient_boosting.py's encoding logic and fit/predict
round-trip — no DB, synthetic data only.
"""

import math

from ml.gradient_boosting import GradientBoostingPredictor


def _record(
    distance_m: float,
    rolling_weekly_mileage_m: float | None = 20_000.0,
    distance_category: str | None = "olympic",
    taper_indicator: bool | None = True,
) -> dict:
    return {
        "target_distance_m": distance_m,
        "distance_category": distance_category,
        "rolling_weekly_mileage_m": rolling_weekly_mileage_m,
        "rolling_weekly_duration_s": 20_000.0,
        "long_run_distance_4wk_m": 15_000.0,
        "days_since_last_hard_effort": 7,
        "taper_indicator": taper_indicator,
        "avg_hr_available": True,
        "avg_power_available": False,
        "feature_window_days": 28,
    }


def test_fit_predict_round_trip_produces_finite_numbers() -> None:
    predictor = GradientBoostingPredictor()
    distances = (25_750.0, 51_500.0, 113_000.0, 226_000.0, 25_750.0, 51_500.0)
    X = [_record(distance_m=d) for d in distances]
    y = [5_400.0, 12_000.0, 28_000.0, 55_000.0, 5_600.0, 12_500.0]

    predictor.fit(X, y)
    predictions = predictor.predict(X)

    assert len(predictions) == len(X)
    assert all(isinstance(p, float) and math.isfinite(p) for p in predictions)


def test_missing_values_do_not_raise() -> None:
    # None for rolling_weekly_mileage_m and taper_indicator -- HistGradientBoostingRegressor
    # must accept NaN natively rather than the encoder raising or crashing sklearn.
    predictor = GradientBoostingPredictor()
    X = [
        _record(distance_m=25_750.0, rolling_weekly_mileage_m=None, taper_indicator=None),
        _record(distance_m=51_500.0),
        _record(distance_m=113_000.0, rolling_weekly_mileage_m=None),
    ]
    y = [5_400.0, 12_000.0, 28_000.0]

    predictor.fit(X, y)
    predictions = predictor.predict(X)

    assert all(math.isfinite(p) for p in predictions)


def test_unseen_distance_category_at_predict_time_does_not_raise() -> None:
    predictor = GradientBoostingPredictor()
    X = [_record(distance_m=d, distance_category="sprint") for d in (25_750.0, 26_000.0, 25_500.0)]
    y = [5_400.0, 5_500.0, 5_300.0]
    predictor.fit(X, y)

    # "full" never appeared during fit -- the fixed one-hot column set must
    # still produce a valid (all-zero-for-that-category) encoding, not an error.
    predictions = predictor.predict([_record(distance_m=226_000.0, distance_category="full")])

    assert len(predictions) == 1
    assert math.isfinite(predictions[0])


def test_missing_distance_category_does_not_raise() -> None:
    predictor = GradientBoostingPredictor()
    X = [_record(distance_m=d, distance_category=None) for d in (25_750.0, 51_500.0)]
    y = [5_400.0, 12_000.0]

    predictor.fit(X, y)
    predictions = predictor.predict(X)

    assert all(math.isfinite(p) for p in predictions)
