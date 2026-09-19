"""All DB access for the `activities` table.

WHAT: upsert-by-natural-key, plus the two read patterns Phase 2+ code needs
— one user's full activity history, and "everything strictly before a given
race" for feature engineering.

WHY upsert, not insert-only: a user can trigger another backfill (a
reconnect, or a future periodic resync), and Strava's own data for an
activity can change after the fact (edited title, corrected distance) —
re-ingesting the same `strava_activity_id` should update the existing row,
not fail the unique constraint or create a duplicate.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Activity


def get_by_strava_id(
    db: Session, *, user_id: uuid.UUID, strava_activity_id: int
) -> Activity | None:
    return db.scalar(
        select(Activity).where(
            Activity.user_id == user_id, Activity.strava_activity_id == strava_activity_id
        )
    )


def upsert_activity(db: Session, fields: dict) -> Activity:
    existing = get_by_strava_id(
        db, user_id=fields["user_id"], strava_activity_id=fields["strava_activity_id"]
    )
    if existing is None:
        activity = Activity(**fields)
        db.add(activity)
    else:
        for key, value in fields.items():
            setattr(existing, key, value)
        activity = existing
    db.commit()
    db.refresh(activity)
    return activity


def list_for_user(db: Session, user_id: uuid.UUID) -> list[Activity]:
    return list(
        db.scalars(
            select(Activity).where(Activity.user_id == user_id).order_by(Activity.start_date)
        )
    )


def list_prior_activities(db: Session, *, user_id: uuid.UUID, before: datetime) -> list[Activity]:
    return list(
        db.scalars(
            select(Activity)
            .where(Activity.user_id == user_id, Activity.start_date < before)
            .order_by(Activity.start_date)
        )
    )
