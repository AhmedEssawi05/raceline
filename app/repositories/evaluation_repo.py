"""All DB access for `eval_runs`, `athlete_splits`, and `eval_metrics`.

WHAT: creation helpers used only by `evaluation/report.py`, plus the reads
Phase 6's scoreboard needs (`get_latest_eval_run`, `list_metrics_for_run`) —
DESIGN.md's note that the scoreboard "reads the latest eval_run's rows
rather than computing anything live" is what these two functions implement.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.evaluation import AthleteSplit, EvalMetric, EvalRun


def create_eval_run(
    db: Session,
    *,
    model_version_id: uuid.UUID,
    split_seed: int,
    n_races_total: int,
    n_athletes_test: int,
    notes: str | None = None,
) -> EvalRun:
    eval_run = EvalRun(
        model_version_id=model_version_id,
        split_seed=split_seed,
        n_races_total=n_races_total,
        n_athletes_test=n_athletes_test,
        notes=notes,
    )
    db.add(eval_run)
    db.commit()
    db.refresh(eval_run)
    return eval_run


def persist_splits(db: Session, *, eval_run_id: uuid.UUID, split: dict[uuid.UUID, str]) -> None:
    for user_id, assignment in split.items():
        db.add(AthleteSplit(eval_run_id=eval_run_id, user_id=user_id, split=assignment))
    db.commit()


def create_eval_metric(
    db: Session,
    *,
    eval_run_id: uuid.UUID,
    method: str,
    distance_category: str | None,
    metrics: dict,
) -> EvalMetric:
    row = EvalMetric(
        eval_run_id=eval_run_id,
        method=method,
        distance_category=distance_category,
        n_races=metrics["n_races"],
        mae_minutes=metrics["mae_minutes"],
        rmse_minutes=metrics["rmse_minutes"],
        mae_pct=metrics["mae_pct"],
        rmse_pct=metrics["rmse_pct"],
    )
    db.add(row)
    db.commit()
    return row


def get_latest_eval_run(db: Session) -> EvalRun | None:
    return db.scalar(select(EvalRun).order_by(EvalRun.run_at.desc()).limit(1))


def list_metrics_for_run(db: Session, eval_run_id: uuid.UUID) -> list[EvalMetric]:
    return list(db.scalars(select(EvalMetric).where(EvalMetric.eval_run_id == eval_run_id)))
