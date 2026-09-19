"""CLI: apply an already-trained `model_version` to a (possibly different)
set of races.

WHAT: `run(model_version_id, athlete_ids=None)` loads the fitted predictor
artifact for `model_version_id` (`joblib.load`) and writes `trained_model`
predictions, tied to that `model_version_id`, for every race in
`ml/features.build_feature_matrix`'s output — restricted to `athlete_ids`
if given.

WHY this is separate from `ml/train.py`, rather than having `train.py` both
fit AND predict on an arbitrary athlete set: `ml/train.py`'s own predictions
are a same-run, same-athletes sanity check (see its docstring — "not a
claim about generalization"). Phase 5's evaluation needs to apply an
*already-fitted* model to a *different* athlete population — test-split
athletes the model never trained on. This module is what
`evaluation/report.py` uses for that: reusing the already-fitted model
loaded from disk (instead of retraining) is what makes "the model that
produced this prediction is exactly the model behind `model_version_id`"
actually true.
"""

import uuid

import joblib

from app.db import SessionLocal
from app.models.prediction import ModelVersion
from app.repositories import prediction_repo
from ml.features import FEATURE_COLUMNS, build_feature_matrix


def run(model_version_id: uuid.UUID, athlete_ids: list[uuid.UUID] | None = None) -> int:
    db = SessionLocal()
    try:
        model_version = db.get(ModelVersion, model_version_id)
        if model_version is None:
            raise ValueError(f"No such model_version: {model_version_id}")

        predictor = joblib.load(model_version.artifact_path)

        df = build_feature_matrix(db, athlete_ids=athlete_ids)
        if df.empty:
            return 0

        records = df[FEATURE_COLUMNS].to_dict(orient="records")
        predictions = predictor.predict(records)
        for activity_id, predicted in zip(df["activity_id"], predictions, strict=True):
            prediction_repo.upsert_prediction(
                db,
                activity_id=uuid.UUID(activity_id),
                method=predictor.method_name,
                predicted_finish_time_s=predicted,
                model_version_id=model_version.id,
                notes=None,
            )
        return len(records)
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_version_id", type=str)
    parser.add_argument("--athlete-ids", type=str, default=None)
    args = parser.parse_args()
    ids = (
        [uuid.UUID(id_.strip()) for id_ in args.athlete_ids.split(",")]
        if args.athlete_ids
        else None
    )

    written = run(uuid.UUID(args.model_version_id), athlete_ids=ids)
    print(f"Wrote {written} trained_model prediction(s).")
