"""Tests for evaluation/metrics.py — pure function, no DB."""

import math

from evaluation.metrics import compute_metrics


def test_perfect_predictions_have_zero_error() -> None:
    metrics = compute_metrics([(3600.0, 3600.0), (7200.0, 7200.0)])

    assert metrics["n_races"] == 2
    assert metrics["mae_minutes"] == 0.0
    assert metrics["rmse_minutes"] == 0.0
    assert metrics["mae_pct"] == 0.0
    assert metrics["rmse_pct"] == 0.0


def test_mae_and_rmse_in_minutes_are_computed_correctly() -> None:
    # Errors of 60s and 120s -> mean abs error 90s = 1.5 min.
    metrics = compute_metrics([(3600.0, 3660.0), (3600.0, 3480.0)])

    assert metrics["mae_minutes"] == 1.5
    assert metrics["rmse_minutes"] == math.sqrt((60**2 + 120**2) / 2) / 60


def test_pct_error_is_relative_to_actual_finish_time() -> None:
    # 60s error on a 3600s (1hr) race is 60/3600 = 1.67%; on a 7200s race, 0.83%.
    metrics = compute_metrics([(3600.0, 3660.0), (7200.0, 7260.0)])

    expected_mae_pct = ((60 / 3600) * 100 + (60 / 7200) * 100) / 2
    assert metrics["mae_pct"] == expected_mae_pct


def test_none_predictions_are_excluded_not_treated_as_zero_error() -> None:
    metrics = compute_metrics([(3600.0, 3600.0), (3600.0, None)])

    assert metrics["n_races"] == 1
    assert metrics["mae_minutes"] == 0.0


def test_all_none_predictions_yield_null_metrics_not_a_crash() -> None:
    metrics = compute_metrics([(3600.0, None), (7200.0, None)])

    assert metrics == {
        "n_races": 0,
        "mae_minutes": None,
        "rmse_minutes": None,
        "mae_pct": None,
        "rmse_pct": None,
    }


def test_empty_input_yields_null_metrics() -> None:
    assert compute_metrics([]) == {
        "n_races": 0,
        "mae_minutes": None,
        "rmse_minutes": None,
        "mae_pct": None,
        "rmse_pct": None,
    }
