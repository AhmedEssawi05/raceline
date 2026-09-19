"""Evaluation report — the project's core deliverable: an honest,
by-athlete-generalization comparison of `riegel` / `strava_estimate` /
`trained_model` against real race results.

WHAT: `run_report(seed=...)` assigns a deterministic athlete train/test
split (`evaluation/split.py`), trains a fresh `trained_model` on train-split
athletes only (reusing `ml/train.py`'s existing `athlete_ids` hook),
generates `riegel` and `trained_model` predictions for test-split athletes'
races plus explanatory `strava_estimate` rows, computes MAE/RMSE (minutes
and % of finish time) per method and per distance category
(`evaluation/metrics.py`), and persists one `eval_runs` row plus its
`eval_metrics` rows.

WHY this reuses `ml/train.py` / `ml/predict_riegel.py` / `ml/predict_trained_model.py`
rather than duplicating fit/predict logic here: those scripts already
accept an `athlete_ids` filter specifically so this module could call them
train-split-only or test-split-only (see their own docstrings) —
re-implementing fit/predict here would risk this evaluation's model
silently drifting from Phase 4's actual training code.

WHY `trained_model` predictions are regenerated for the test set via
`ml/predict_trained_model.py`, separately from the predictions `ml/train.py`
already wrote for the train set: `ml/train.py`'s own predictions are a
same-run, same-athletes sanity check (see its docstring) — this evaluation
needs the model applied to athletes it *never saw during fitting*, which is
a different call using the exact same fitted artifact (`joblib.load`), not
a retrain.

WHY `strava_estimate` gets `predictions` rows here even though it can never
predict anything (DESIGN.md's Explicit Flags item 1): the comparison table
is supposed to always list all three methods, with `strava_estimate`'s
`n_races=0`/null metrics being the explicit, honest "unavailable" signal —
not a method silently missing from the report.

HOW distance-category breakdown works: for each method, one `eval_metrics`
row is always written with `distance_category=None` (all test races for
that method, combined); one additional row is written per distance category
actually present among the test set's races — a category with zero test
races simply gets no row for that category, rather than a fabricated empty
one.
"""

import uuid
from pathlib import Path

from app.db import SessionLocal
from app.repositories import evaluation_repo, prediction_repo, race_repo, user_repo
from evaluation.metrics import compute_metrics
from evaluation.split import assign_splits
from ml.predict_riegel import run as run_riegel_predictions
from ml.predict_trained_model import run as run_trained_model_predictions
from ml.strava_estimate import UNAVAILABLE_NOTE, StravaEstimatePredictor
from ml.train import DEFAULT_ARTIFACT_DIR
from ml.train import run as run_training

DEFAULT_SEED = 42
METHODS = ("riegel", "strava_estimate", "trained_model")


def run_report(seed: int = DEFAULT_SEED, artifact_dir: Path = DEFAULT_ARTIFACT_DIR) -> uuid.UUID:
    db = SessionLocal()
    try:
        user_ids = [user.id for user in user_repo.list_active(db)]
        split = assign_splits(user_ids, seed)
        train_ids = [uid for uid, assignment in split.items() if assignment == "train"]
        test_ids = [uid for uid, assignment in split.items() if assignment == "test"]

        model_version_id = run_training(athlete_ids=train_ids, artifact_dir=artifact_dir)

        n_races_total = sum(
            len(race_repo.list_races_with_finish_time(db, uid)) for uid in test_ids
        )
        eval_run = evaluation_repo.create_eval_run(
            db,
            model_version_id=model_version_id,
            split_seed=seed,
            n_races_total=n_races_total,
            n_athletes_test=len(test_ids),
        )
        evaluation_repo.persist_splits(db, eval_run_id=eval_run.id, split=split)

        run_trained_model_predictions(model_version_id, athlete_ids=test_ids)
        run_riegel_predictions(athlete_ids=test_ids)
        _write_strava_estimate_predictions(db, test_ids)

        all_predictions = prediction_repo.list_predictions_for_eval(db, test_ids)
        categories = sorted(
            {category for _, category, _, _ in all_predictions if category is not None}
        )

        for method in METHODS:
            method_pairs = [
                (actual, predicted)
                for m, _category, actual, predicted in all_predictions
                if m == method
            ]
            evaluation_repo.create_eval_metric(
                db,
                eval_run_id=eval_run.id,
                method=method,
                distance_category=None,
                metrics=compute_metrics(method_pairs),
            )
            for category in categories:
                category_pairs = [
                    (actual, predicted)
                    for m, c, actual, predicted in all_predictions
                    if m == method and c == category
                ]
                evaluation_repo.create_eval_metric(
                    db,
                    eval_run_id=eval_run.id,
                    method=method,
                    distance_category=category,
                    metrics=compute_metrics(category_pairs),
                )

        return eval_run.id
    finally:
        db.close()


def _write_strava_estimate_predictions(db, athlete_ids: list[uuid.UUID]) -> int:
    written = 0
    for user_id in athlete_ids:
        for activity, _detail in race_repo.list_races_with_finish_time(db, user_id):
            prediction_repo.upsert_prediction(
                db,
                activity_id=activity.id,
                method=StravaEstimatePredictor.method_name,
                predicted_finish_time_s=None,
                model_version_id=None,
                notes=UNAVAILABLE_NOTE,
            )
            written += 1
    return written
