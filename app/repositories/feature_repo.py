"""All DB access for `training_load_features` — one upsert keyed by the
race's `activity_id`, matching the "one row per race, rerun overwrites"
contract in worker/jobs/compute_features.py, plus the wider read
`ml/features.py` needs to build the trained model's feature matrix.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.features import TrainingLoadFeatures
from app.models.race import RaceClassification, RaceDetail


def get_for_activity(db: Session, activity_id: uuid.UUID) -> TrainingLoadFeatures | None:
    return db.scalar(
        select(TrainingLoadFeatures).where(TrainingLoadFeatures.activity_id == activity_id)
    )


def list_races_with_features(
    db: Session, athlete_ids: list[uuid.UUID] | None = None
) -> list[tuple[Activity, RaceClassification, TrainingLoadFeatures, RaceDetail]]:
    """Every effectively-classified race that has both computed
    training-load features and a known finish time — "usable training data"
    for `ml/features.build_feature_matrix`. `athlete_ids=None` means every
    athlete; a specific list is how Phase 5's evaluation will restrict
    training to train-split athletes only (see DESIGN.md's Phase 4 note).
    """
    query = (
        select(Activity, RaceClassification, TrainingLoadFeatures, RaceDetail)
        .join(RaceClassification, RaceClassification.activity_id == Activity.id)
        .join(TrainingLoadFeatures, TrainingLoadFeatures.activity_id == Activity.id)
        .join(RaceDetail, RaceDetail.activity_id == Activity.id)
        .where(
            RaceClassification.is_race_effective.is_(True),
            RaceDetail.finish_time_s.is_not(None),
        )
        .order_by(Activity.start_date)
    )
    if athlete_ids is not None:
        query = query.where(Activity.user_id.in_(athlete_ids))
    return [tuple(row) for row in db.execute(query).all()]


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
