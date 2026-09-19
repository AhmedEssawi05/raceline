"""Riegel's formula — the zero-training-data baseline predictor.

WHAT: `RiegelPredictor` extrapolates a target race's finish time from one
reference performance (a different race, of a different distance, with a
known finish time) using Peter Riegel's 1977 formula:

    T2 = T1 * (D2 / D1) ** RIEGEL_EXPONENT

WHY this baseline exists at all (per spec): it's the standard, well-known
endurance-prediction formula a reviewer will already recognize — a trained
model (Phase 4) has to beat *this*, not just guess the mean, for its
accuracy claim to mean anything.

EXPLICIT LIMITATION — read before trusting this baseline's numbers: Riegel's
formula was derived from single-sport running data and models pure
fatigue/endurance decay with distance. Applying it to triathlon *total*
race time (swim + T1 + bike + T2 + run) is an approximation this project
uses anyway, since there's no established multisport equivalent in wide
use — it ignores discipline mix, transition time, and pacing-strategy
differences between, say, a sprint and a 70.3. `RiegelPredictor` is
deliberately the weakest baseline in the comparison for this reason;
DESIGN.md's evaluation report (Phase 5) is expected to surface its accuracy
honestly rather than the code silently treating it as ground truth.

WHY `fit` is a documented no-op: Riegel's formula has no parameters to
learn from training data — see ml/interface.py for why this is still
implemented explicitly rather than omitted.

WHY a missing reference performance yields `None`, not a fabricated guess
(e.g. the target distance's typical finish time): a formula that
extrapolates from nothing isn't a prediction, it's a lookup table in
disguise. A null `predictions.predicted_finish_time_s` is the honest
signal that this athlete has no usable baseline yet for this race — the
same null-over-fabrication principle DESIGN.md applies to
`race_details`/`training_load_features`.

HOW `predict`'s input records are shaped: each dict needs
`reference_distance_m`, `reference_time_s` (the prior race) and
`target_distance_m` (the race being predicted) — built by
`ml/predict_riegel.py`, which owns the decision of *which* prior race
counts as the reference.
"""

from collections.abc import Sequence
from typing import Any

from ml.interface import Predictor

RIEGEL_EXPONENT = 1.06


class RiegelPredictor(Predictor):
    method_name = "riegel"

    def fit(self, X: Sequence[dict[str, Any]], y: Sequence[float]) -> None:
        pass  # no parameters to learn -- see module docstring

    def predict(self, X: Sequence[dict[str, Any]]) -> list[float | None]:
        return [self._predict_one(record) for record in X]

    @staticmethod
    def _predict_one(record: dict[str, Any]) -> float | None:
        reference_distance_m = record.get("reference_distance_m")
        reference_time_s = record.get("reference_time_s")
        target_distance_m = record.get("target_distance_m")
        if not reference_distance_m or not reference_time_s or not target_distance_m:
            return None
        return reference_time_s * (target_distance_m / reference_distance_m) ** RIEGEL_EXPONENT
