"""Tests for ml/riegel.py — pure formula correctness, no DB.

Also covers ml/interface.py's contract indirectly: `RiegelPredictor` is the
only concrete `Predictor` that exists yet, so exercising it here is what
proves the abstract base class is actually implementable as designed.
"""

from ml.registry import get_predictor
from ml.riegel import RIEGEL_EXPONENT, RiegelPredictor


def test_predicts_using_riegels_formula() -> None:
    predictor = RiegelPredictor()
    # 5,000m in 1,200s (20:00) extrapolated to 10,000m.
    record = {
        "reference_distance_m": 5_000.0,
        "reference_time_s": 1_200.0,
        "target_distance_m": 10_000.0,
    }

    [predicted] = predictor.predict([record])

    expected = 1_200.0 * (10_000.0 / 5_000.0) ** RIEGEL_EXPONENT
    assert predicted == expected


def test_predicting_a_longer_distance_costs_more_than_linear_scaling() -> None:
    # The exponent (>1) models fatigue -- doubling distance should cost
    # more than double the time, not exactly double.
    predictor = RiegelPredictor()
    record = {
        "reference_distance_m": 5_000.0,
        "reference_time_s": 1_200.0,
        "target_distance_m": 10_000.0,
    }

    [predicted] = predictor.predict([record])

    linear_scaling = 1_200.0 * 2
    assert predicted > linear_scaling


def test_returns_none_without_a_reference_performance() -> None:
    predictor = RiegelPredictor()

    predictions = predictor.predict(
        [
            {"reference_distance_m": None, "reference_time_s": None, "target_distance_m": 10_000.0},
            {},
        ]
    )

    assert predictions == [None, None]


def test_fit_is_a_documented_noop() -> None:
    predictor = RiegelPredictor()

    predictor.fit([], [])  # must not raise -- there is nothing to learn

    record = {
        "reference_distance_m": 5_000.0,
        "reference_time_s": 1_200.0,
        "target_distance_m": 10_000.0,
    }
    assert predictor.predict([record]) != [None]


def test_registry_returns_a_riegel_predictor() -> None:
    predictor = get_predictor("riegel")

    assert isinstance(predictor, RiegelPredictor)
    assert predictor.method_name == "riegel"
