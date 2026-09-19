"""Tests for ml/strava_estimate.py — a trivial but load-bearing stub, since
DESIGN.md's Explicit Flags item 1 depends on it always behaving this way.
"""

from ml.registry import get_predictor
from ml.strava_estimate import StravaEstimatePredictor


def test_predict_always_returns_none() -> None:
    predictor = StravaEstimatePredictor()

    predictions = predictor.predict([{}, {"anything": 1}, {}])

    assert predictions == [None, None, None]


def test_fit_is_a_documented_noop() -> None:
    StravaEstimatePredictor().fit([], [])  # must not raise


def test_registry_returns_a_strava_estimate_predictor() -> None:
    predictor = get_predictor("strava_estimate")

    assert isinstance(predictor, StravaEstimatePredictor)
    assert predictor.method_name == "strava_estimate"
