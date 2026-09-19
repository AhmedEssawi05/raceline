"""All DB access for `training_load_features` — one upsert keyed by the
race's `activity_id`, matching the "one row per race, rerun overwrites"
contract in worker/jobs/compute_features.py.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.features import TrainingLoadFeatures


def get_for_activity(db: Session, activity_id: uuid.UUID) -> TrainingLoadFeatures | None:
    return db.scalar(
        select(TrainingLoadFeatures).where(TrainingLoadFeatures.activity_id == activity_id)
    )


def upsert_features(db: Session, *, activity: Activity, features: dict) -> TrainingLoadFeatures:
    existing = get_for_activity(db, activity.id)
    if existing is None:
        existing = TrainingLoadFeatures(activity_id=activity.id)
        db.add(existing)
    for key, value in features.items():
        setattr(existing, key, value)
    existing.computed_at = datetime.now(UTC)
    db.commit()
    db.refresh(existing)
    return existing
