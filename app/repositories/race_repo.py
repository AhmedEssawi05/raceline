"""All DB access for `race_classifications` and `race_details`.

WHAT: upsert-by-`activity_id` for both tables, the manual-override write,
and the "this user's effective races" read the races router needs.

WHY manual override is its own narrow function rather than a generic
"update classification": it only ever touches `manual_override`, never
`heuristic_is_race` — that's what keeps the heuristic's original verdict
intact for audit/debugging even after a user overrides it (see
app/models/race.py for why those are separate columns).

WHY `record_detail_fetch_error` and `upsert_detail` both create the row on
first write rather than requiring it to pre-exist: a race can fail its
first detail-fetch attempt before ever succeeding, so `race_details` must be
writable to record *just* the failure — `fetch_error` needs a row to live
on for the retry path to check.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.race import RaceClassification, RaceDetail


def get_classification(db: Session, activity_id: uuid.UUID) -> RaceClassification | None:
    return db.scalar(
        select(RaceClassification).where(RaceClassification.activity_id == activity_id)
    )


def upsert_classification(
    db: Session,
    *,
    activity: Activity,
    heuristic_is_race: bool,
    heuristic_matched_pattern: str | None,
    distance_category: str | None,
) -> RaceClassification:
    existing = get_classification(db, activity.id)
    if existing is None:
        existing = RaceClassification(activity_id=activity.id)
        db.add(existing)
    existing.heuristic_is_race = heuristic_is_race
    existing.heuristic_matched_pattern = heuristic_matched_pattern
    existing.distance_category = distance_category
    existing.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(existing)
    return existing


def set_manual_override(
    db: Session, classification: RaceClassification, override: bool | None
) -> RaceClassification:
    classification.manual_override = override
    classification.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(classification)
    return classification


def list_races_for_user(
    db: Session, user_id: uuid.UUID
) -> list[tuple[Activity, RaceClassification]]:
    rows = db.execute(
        select(Activity, RaceClassification)
        .join(RaceClassification, RaceClassification.activity_id == Activity.id)
        .where(Activity.user_id == user_id, RaceClassification.is_race_effective.is_(True))
        .order_by(Activity.start_date.desc())
    ).all()
    return [(row[0], row[1]) for row in rows]


def list_races_with_finish_time(
    db: Session, user_id: uuid.UUID
) -> list[tuple[Activity, RaceDetail]]:
    """This user's effectively-classified races that have a known finish
    time, ordered oldest-first — the shape `ml/predict_riegel.py` needs to
    walk chronologically and pick each race's reference performance from
    the one immediately before it.
    """
    rows = db.execute(
        select(Activity, RaceDetail)
        .join(RaceClassification, RaceClassification.activity_id == Activity.id)
        .join(RaceDetail, RaceDetail.activity_id == Activity.id)
        .where(
            Activity.user_id == user_id,
            RaceClassification.is_race_effective.is_(True),
            RaceDetail.finish_time_s.is_not(None),
        )
        .order_by(Activity.start_date)
    ).all()
    return [(row[0], row[1]) for row in rows]


def get_detail(db: Session, activity_id: uuid.UUID) -> RaceDetail | None:
    return db.scalar(select(RaceDetail).where(RaceDetail.activity_id == activity_id))


def get_details_for_activities(
    db: Session, activity_ids: list[uuid.UUID]
) -> dict[uuid.UUID, RaceDetail]:
    """`{activity_id: RaceDetail}` for the given activities — batches what
    the Phase 6 race-list dashboard would otherwise do as one `get_detail`
    call per row.
    """
    if not activity_ids:
        return {}
    details = db.scalars(
        select(RaceDetail).where(RaceDetail.activity_id.in_(activity_ids))
    ).all()
    return {detail.activity_id: detail for detail in details}


def _get_or_create_detail(db: Session, activity_id: uuid.UUID) -> RaceDetail:
    existing = get_detail(db, activity_id)
    if existing is None:
        existing = RaceDetail(activity_id=activity_id)
        db.add(existing)
    return existing


def upsert_detail(
    db: Session,
    *,
    activity: Activity,
    splits: dict | list | None,
    elevation_profile: dict | list | None,
    finish_time_s: int | None,
) -> RaceDetail:
    detail = _get_or_create_detail(db, activity.id)
    detail.splits = splits
    detail.elevation_profile = elevation_profile
    detail.finish_time_s = finish_time_s
    detail.fetch_error = None
    detail.fetched_at = datetime.now(UTC)
    db.commit()
    db.refresh(detail)
    return detail


def record_detail_fetch_error(db: Session, activity: Activity, *, error: str) -> RaceDetail:
    detail = _get_or_create_detail(db, activity.id)
    detail.fetch_error = error
    detail.fetched_at = datetime.now(UTC)
    db.commit()
    db.refresh(detail)
    return detail
