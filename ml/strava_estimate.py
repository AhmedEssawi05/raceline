"""StravaEstimatePredictor — Strava's predicted-finish-time method, always
unavailable.

WHAT: implements `Predictor` with `fit` a no-op and `predict` always
returning `None` for every input, plus a fixed explanatory note.

WHY this class exists at all instead of omitting `strava_estimate` from the
comparison (DESIGN.md's Explicit Flags item 1): no predicted-finish-time
field exists in Strava API v3 — this project's own fallback instruction is
that this comparison is *not* built via scraping, and segment-leaderboard
data is deliberately not used as a substitute proxy either (item 2 in that
same list), since that would misrepresent the comparison. Existing
structurally, implementing the same interface as `riegel`/`trained_model`,
is what lets `evaluation/report.py` loop over all three methods uniformly
and produce an honest, explicit "unavailable" row — `n_races = 0`, null
metrics — instead of a method silently missing from a report a reviewer
would expect to see it in.
"""

from collections.abc import Sequence
from typing import Any

from ml.interface import Predictor

UNAVAILABLE_NOTE = "unavailable: Strava API does not expose a predicted finish time"


class StravaEstimatePredictor(Predictor):
    method_name = "strava_estimate"

    def fit(self, X: Sequence[dict[str, Any]], y: Sequence[float]) -> None:
        pass  # nothing to train -- see module docstring

    def predict(self, X: Sequence[dict[str, Any]]) -> list[float | None]:
        return [None] * len(X)
