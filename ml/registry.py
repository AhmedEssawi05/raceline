"""Predictor registry — maps a `predictions.method` string to the concrete
`Predictor` class that implements it.

WHY a registry dict instead of importing concrete classes at call sites:
`ml/predict_riegel.py` now, and `ml/train.py`/`evaluation/report.py` in
later phases, only ever call `get_predictor(name)` — swapping which
algorithm backs `trained_model`, or adding a new method entirely, is a
one-line addition here, with zero changes to training or evaluation code.
See DESIGN.md's "swappable-model mechanism."
"""

from ml.interface import Predictor
from ml.riegel import RiegelPredictor

PREDICTOR_REGISTRY: dict[str, type[Predictor]] = {
    "riegel": RiegelPredictor,
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
