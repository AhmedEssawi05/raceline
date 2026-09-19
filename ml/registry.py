"""Predictor registry — maps a config/algorithm string to the concrete
`Predictor` class that implements it.

WHY the registry key is an *algorithm* name (`"gradient_boosting"`), not the
`predictions.method` value it produces: `predictions.method` only has three
allowed values (`riegel`/`strava_estimate`/`trained_model`), but multiple
algorithms could all produce `trained_model` rows — DESIGN.md's swappable-
model example is exactly this, swapping gradient boosting for
`ml/linear_baseline.py`'s linear regression without either one meaning
something different in `predictions.method`. `app/config.py`'s
`trained_model_algorithm` (env var `RACELINE_MODEL_ALGORITHM`, default
`"gradient_boosting"`) is what selects *which* registry entry currently
backs the single `trained_model` slot. `riegel` is the one entry where the
algorithm name and the method name happen to coincide, since it's a
standalone baseline with no alternative implementation.

WHY a registry dict instead of importing concrete classes at call sites:
`ml/predict_riegel.py` and `ml/train.py` now, and `evaluation/report.py` in
Phase 5, only ever call `get_predictor(name)` — adding a new algorithm, or
changing which one is active, is a one-line registration plus an env var
change, with zero changes to training or evaluation code.

WHY `get_predictor` always returns a fresh, unfit instance rather than a
cached/fitted one: that's the right shape for both callers — Riegel's `fit`
is a no-op so it's already "ready," and `ml/train.py` explicitly wants a
blank model to call `.fit(X, y)` on. Loading an *already-fitted*
`trained_model` for a specific past `model_version_id` (to regenerate
predictions from a completed training run) is a different concern — that
goes through `joblib.load(model_version.artifact_path)`, not this registry.
"""

from ml.gradient_boosting import GradientBoostingPredictor
from ml.interface import Predictor
from ml.riegel import RiegelPredictor

PREDICTOR_REGISTRY: dict[str, type[Predictor]] = {
    "riegel": RiegelPredictor,
    "gradient_boosting": GradientBoostingPredictor,
}


def get_predictor(method: str) -> Predictor:
    try:
        predictor_cls = PREDICTOR_REGISTRY[method]
    except KeyError:
        raise ValueError(
            f"Unknown predictor method {method!r}. Registered methods: "
            f"{sorted(PREDICTOR_REGISTRY)}"
        ) from None
    return predictor_cls()
