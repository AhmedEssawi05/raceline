"""Gradient-boosting trained-model predictor — Phase 4's `trained_model`
method.

WHAT: `GradientBoostingPredictor` wraps scikit-learn's
`HistGradientBoostingRegressor`, encoding `ml/features.py`'s feature-matrix
columns into the numeric matrix sklearn requires.

WHY `HistGradientBoostingRegressor`, not the older `GradientBoostingRegressor`
(despite this module's name and DESIGN.md's original "sklearn GBR wrapper"
phrasing): this project's whole feature set is built around *explicit*
missing values — `training_load_features`' null contract means insufficient
trailing history is `None`, never a fabricated 0 (app/models/features.py).
`HistGradientBoostingRegressor` is the scikit-learn estimator that accepts
NaN directly and splits around it, rather than requiring an upstream
imputer. Imputing (e.g. filling a missing `rolling_weekly_mileage_m` with 0
or a mean) would misrepresent "we don't know this athlete's recent training
load" as "this athlete didn't train" — exactly the failure mode DESIGN.md
calls out for `avg_heart_rate`/`avg_power_w`. Treating missingness as a
first-class, learnable signal is the closest fit to that principle, so it's
the deliberate choice here despite the name mismatch with DESIGN.md's
original shorthand.

WHY `distance_category` is one-hot encoded to a *fixed* column set
(`_DISTANCE_CATEGORIES`), not `pandas.get_dummies` on whatever categories
happen to appear in a given call: `fit` and `predict` are almost never
called on the same data — a `predict` call for a single new race would
otherwise produce a different, misaligned column set than the model was
trained on, and sklearn would reject or silently misinterpret it. Fixing
the column set up front (from `race_classifications.distance_category`'s
own enum) guarantees `fit` and `predict` always agree, including for a
category absent from a particular prediction batch.

HOW booleans become numbers: `True`/`False`/`None` map to `1.0`/`0.0`/NaN —
`None` (DESIGN.md's "not computable" state, e.g. for `taper_indicator`)
stays a genuine missing value for the same reason as above, not a
default-to-False guess.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from ml.interface import Predictor

_DISTANCE_CATEGORIES = ["sprint", "olympic", "70.3", "full", "other"]
_NUMERIC_COLUMNS = [
    "target_distance_m",
    "rolling_weekly_mileage_m",
    "rolling_weekly_duration_s",
    "long_run_distance_4wk_m",
    "days_since_last_hard_effort",
    "taper_indicator",
    "avg_hr_available",
    "avg_power_available",
    "feature_window_days",
]


def _to_float(value: Any) -> float:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value)


def _encode(X: Sequence[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(list(X))
    encoded = pd.DataFrame(index=df.index)

    for column in _NUMERIC_COLUMNS:
        series = df[column] if column in df.columns else pd.Series([None] * len(df), index=df.index)
        encoded[column] = series.map(_to_float)

    category_series = (
        df["distance_category"]
        if "distance_category" in df.columns
        else pd.Series([None] * len(df), index=df.index)
    )
    for category in _DISTANCE_CATEGORIES:
        encoded[f"distance_category__{category}"] = (category_series == category).astype(float)

    return encoded


class GradientBoostingPredictor(Predictor):
    method_name = "trained_model"

    def __init__(self) -> None:
        self._model = HistGradientBoostingRegressor(random_state=0)

    def fit(self, X: Sequence[dict[str, Any]], y: Sequence[float]) -> None:
        self._model.fit(_encode(X), np.asarray(y, dtype=float))

    def predict(self, X: Sequence[dict[str, Any]]) -> list[float | None]:
        predictions = self._model.predict(_encode(X))
        return [float(p) for p in predictions]
