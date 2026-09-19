"""All DB access for `predictions`.

WHAT: `upsert_prediction` is the only write path — get-or-create keyed on
`(activity_id, method, model_version_id)`. `list_predictions_for_eval` and
`list_predictions_by_activity` are the reads Phase 5's evaluation report and
Phase 6's race-list dashboard need, respectively.

WHY this upserts via an explicit query-then-write, not a DB-level
`ON CONFLICT`: Postgres treats NULL as distinct from NULL in a unique
constraint, so `riegel`/`strava_estimate` rows (always `model_version_id =
NULL`) can't rely on the table's unique constraint the way `trained_model`
rows can — see app/models/prediction.py's caveat. Querying with
`.where(Prediction.model_version_id == value)` compiles to `IS NULL` when
`value` is `None`, which finds the right existing row (or correctly finds
none) regardless of NULL's constraint semantics.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.prediction import Prediction
from app.models.race import RaceClassification, RaceDetail


def get_prediction(
    db: Session, *, activity_id: uuid.UUID, method: str, model_version_id: uuid.UUID | None
) -> Prediction | None:
    return db.scalar(
        select(Prediction).where(
            Prediction.activity_id == activity_id,
            Prediction.method == method,
            Prediction.model_version_id == model_version_id,
        )
    )


def upsert_prediction(
    db: Session,
    *,
    activity_id: uuid.UUID,
    method: str,
    predicted_finish_time_s: float | None,
    model_version_id: uuid.UUID | None,
    notes: str | None,
) -> Prediction:
    existing = get_prediction(
        db, activity_id=activity_id, method=method, model_version_id=model_version_id
    )
    if existing is None:
        existing = Prediction(
            activity_id=activity_id, method=method, model_version_id=model_version_id
        )
        db.add(existing)
    existing.predicted_finish_time_s = predicted_finish_time_s
    existing.notes = notes
    db.commit()
    db.refresh(existing)
    return existing


def list_predictions_for_eval(
    db: Session, athlete_ids: list[uuid.UUID]
) -> list[tuple[str, str | None, float, float | None]]:
    """`(method, distance_category, actual_finish_time_s,
    predicted_finish_time_s)` for every prediction row belonging to an
    effectively-classified race, with a known actual finish time, owned by
    one of `athlete_ids` — the exact shape `evaluation.metrics.compute_metrics`
    consumes, grouped by `evaluation/report.py` per method and category.
    """
    if not athlete_ids:
        return []
    rows = db.execute(
        select(
            Prediction.method,
            RaceClassification.distance_category,
            RaceDetail.finish_time_s,
            Prediction.predicted_finish_time_s,
        )
        .join(Activity, Activity.id == Prediction.activity_id)
        .join(RaceClassification, RaceClassification.activity_id == Activity.id)
        .join(RaceDetail, RaceDetail.activity_id == Activity.id)
        .where(
            Activity.user_id.in_(athlete_ids),
            RaceClassification.is_race_effective.is_(True),
            RaceDetail.finish_time_s.is_not(None),
        )
    ).all()
    return [tuple(row) for row in rows]


def list_predictions_by_activity(
    db: Session, activity_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, float | None]]:
    """`{activity_id: {method: predicted_finish_time_s}}` for the given
    activities — what the Phase 6 race-list dashboard uses to show
    predicted-vs-actual per race without one query per method per row.
    """
    if not activity_ids:
        return {}
    rows = db.execute(
        select(Prediction.activity_id, Prediction.method, Prediction.predicted_finish_time_s).where(
            Prediction.activity_id.in_(activity_ids)
        )
    ).all()
    result: dict[uuid.UUID, dict[str, float | None]] = {}
    for activity_id, method, predicted_finish_time_s in rows:
        result.setdefault(activity_id, {})[method] = predicted_finish_time_s
    return result
