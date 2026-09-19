"""All DB access for `predictions`.

WHAT: `upsert_prediction` is the only write path — get-or-create keyed on
`(activity_id, method, model_version_id)`.

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

from app.models.prediction import Prediction


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
