"""CLI: train a `trained_model` predictor on real ingested data.

WHAT: `python -m ml.train [--athlete-ids id1,id2,...] [--algorithm name]`
builds the feature matrix (`ml/features.py`), fits the configured algorithm
via `ml/registry.py`, persists the fitted model to
`model_artifacts/<model_version_id>.joblib`, records a `model_versions` row
(with `algorithm` set to whichever registry key was used), and writes
`trained_model` predictions (tied to that `model_version_id`) for every
race it just trained on.

WHY `--athlete-ids` exists (per DESIGN.md's Phase 4 note): this is the hook
Phase 5's evaluation will use to train on train-split athletes only —
`run()` and `ml/features.build_feature_matrix` just accept an explicit id
list (or, with none given, train on every athlete, for this phase's own
standalone demo); neither needs to know what a "split" is.

WHY `--algorithm` defaults to `app.config.Settings.trained_model_algorithm`
(env var `RACELINE_MODEL_ALGORITHM`) rather than a hardcoded string: this is
DESIGN.md's swappable-model mechanism made concrete — swapping which
algorithm backs `trained_model` is a config change (or a one-off `--algorithm`
flag), never a code change to this script.

WHY this script writes predictions on its *own training set*, unlike
`ml/predict_riegel.py`'s per-race skip logic: Phase 4's demo criterion is
"train, persist an artifact, generate predictions, spot-check against
actual finish times" — a sanity check that the pipeline produces plausible
numbers end-to-end, not a claim about generalization. Phase 5's
`evaluation/report.py` is explicitly where this project's honest, held-out
accuracy comparison lives (predictions generated only for test-split
athletes the model never trained on) — this script's predictions should not
be read as that.

HOW the artifact path is chosen: `model_artifacts/` is git-ignored (these
are regenerable binary files, not source) and created if missing; the
filename is the new `model_versions.id`, so `predictions.model_version_id`
and the artifact on disk are always unambiguously the same version.
`artifact_dir` is a parameter (not a hardcoded path) specifically so tests
can point it at a temp directory instead of writing into the repo.
"""

import argparse
import uuid
from pathlib import Path

import joblib

from app.config import get_settings
from app.db import SessionLocal
from app.models.prediction import ModelVersion
from app.repositories import prediction_repo
from ml.features import FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION, build_feature_matrix
from ml.registry import get_predictor

DEFAULT_ARTIFACT_DIR = Path("model_artifacts")


def run(
    athlete_ids: list[uuid.UUID] | None = None,
    algorithm: str | None = None,
    artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
) -> uuid.UUID:
    algorithm = algorithm or get_settings().trained_model_algorithm
    db = SessionLocal()
    try:
        df = build_feature_matrix(db, athlete_ids=athlete_ids)
        if df.empty:
            raise RuntimeError(
                "No races with computed features and a known finish time are available to train on."
            )

        records = df[FEATURE_COLUMNS].to_dict(orient="records")
        y = df["finish_time_s"].tolist()

        predictor = get_predictor(algorithm)
        predictor.fit(records, y)

        model_version = ModelVersion(
            algorithm=algorithm,
            hyperparameters={},
            training_athlete_ids=sorted(df["user_id"].unique().tolist()),
            artifact_path="",  # filled in below, once the row's id is known
            feature_schema_version=FEATURE_SCHEMA_VERSION,
        )
        db.add(model_version)
        db.commit()
        db.refresh(model_version)

        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f"{model_version.id}.joblib"
        joblib.dump(predictor, artifact_path)
        model_version.artifact_path = str(artifact_path)
        db.commit()

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

        return model_version.id
    finally:
        db.close()


def _parse_athlete_ids(raw: str | None) -> list[uuid.UUID] | None:
    if not raw:
        return None
    return [uuid.UUID(id_.strip()) for id_ in raw.split(",")]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--athlete-ids",
        type=str,
        default=None,
        help="Comma-separated user UUIDs to restrict training to (default: all users).",
    )
    parser.add_argument(
        "--algorithm",
        type=str,
        default=None,
        help="Registry key to train (default: RACELINE_MODEL_ALGORITHM, or 'gradient_boosting').",
    )
    args = parser.parse_args()

    trained_model_version_id = run(
        athlete_ids=_parse_athlete_ids(args.athlete_ids), algorithm=args.algorithm
    )
    print(f"Trained model_version {trained_model_version_id}")
