"""Predictor interface — the abstraction every prediction method (Riegel
now; gradient boosting and Strava's stub in later phases) implements, so the
training CLI (Phase 4) and the evaluation report (Phase 5) never import a
concrete predictor class directly.

WHAT: `Predictor` is an ABC with `fit`, `predict`, and a `method_name` class
attribute matching one of `predictions.method`'s allowed values
(`riegel` / `strava_estimate` / `trained_model`).

WHY `fit` is abstract rather than a default no-op inherited from the base
class: DESIGN.md's swappable-model mechanism treats every method uniformly
through this interface specifically so `evaluation/report.py` (Phase 5) can
loop over all registered methods without special-casing "this one doesn't
train." A predictor with nothing to fit (`RiegelPredictor`, and later
`StravaEstimatePredictor`) still has to say so explicitly in its own
docstring, rather than silently inheriting a no-op that could mask a future
subclass that forgot to implement fitting it actually needs.

WHY `predict` takes a sequence of plain dicts, not a pandas DataFrame:
Phase 3's only predictor (Riegel) needs a completely different input shape
than a trained model does — a reference performance to extrapolate from,
not an engineered feature vector. A dict-per-race keeps this interface
honest for both without forcing Riegel's caller to build a DataFrame it
doesn't need. Phase 4's `GradientBoostingPredictor` can still accept the
richer per-race dict `ml/features.py` will produce — nothing here assumes a
fixed key set; that's each concrete predictor's own documented contract.

HOW a new predictor slots in: subclass `Predictor`, implement
`fit`/`predict`, set `method_name`, register it in `ml/registry.py`.
Nothing else in the training/evaluation pipeline needs to change.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any


class Predictor(ABC):
    method_name: str

    @abstractmethod
    def fit(self, X: Sequence[dict[str, Any]], y: Sequence[float]) -> None:
        """Train on `(X, y)`. Implementations with nothing to train
        (Riegel, later the Strava stub) still implement this explicitly as
        a documented no-op — see this module's docstring for why.
        """

    @abstractmethod
    def predict(self, X: Sequence[dict[str, Any]]) -> list[float | None]:
        """Return one predicted finish time (seconds) per input record, in
        the same order. `None` means "this method can't produce a
        prediction for this input" (e.g. Riegel with no reference
        performance to extrapolate from) — never a fabricated number.
        """
