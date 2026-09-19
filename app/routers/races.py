"""Backfill trigger/status, the race list, and the manual-override toggle.

WHAT: `/races/backfill` enqueues a backfill for the current user, creating
its `backfill_jobs` row synchronously so a status is immediately pollable;
`/races/backfill/status` reports the latest run; `GET /races` lists this
user's effectively-classified races; `/races/{activity_id}/override`
implements the manual-override toggle DESIGN.md calls out as a bare
endpoint built ahead of the dashboard, to validate the schema end-to-end —
the same pattern Phase 1 used for `/auth/status`.

WHY the override endpoint takes an activity id from the URL, which looks
like it conflicts with app/deps.py's "never a spoofable route parameter"
rule: that rule is about *whose data* a route reads (always the session
user, never a caller-supplied user id) — it's not a ban on path parameters
in general. This endpoint still resolves `get_current_user()` from the
session and verifies the target activity belongs to that user before
touching it, so a caller can only ever override their own races.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models.activity import Activity
from app.models.backfill_job import BackfillJob
from app.models.user import User
from app.repositories import backfill_job_repo, race_repo
from app.schemas.race import BackfillStatus, ManualOverrideRequest, RaceSummary
from worker.jobs.backfill import run_backfill
from worker.queue import queue

router = APIRouter(prefix="/races", tags=["races"])


def _to_status(job: BackfillJob) -> BackfillStatus:
    return BackfillStatus(
        status=job.status,
        pages_fetched=job.pages_fetched,
        activities_ingested=job.activities_ingested,
        activities_failed=job.activities_failed,
        started_at=job.started_at,
        finished_at=job.finished_at,
        last_error=job.last_error,
    )


@router.post("/backfill", response_model=BackfillStatus)
def start_backfill(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> BackfillStatus:
    job = backfill_job_repo.create(db, user_id=user.id)
    rq_job = queue.enqueue(run_backfill, str(user.id), str(job.id))
    backfill_job_repo.set_rq_job_id(db, job, rq_job.id)
    return _to_status(job)


@router.get("/backfill/status", response_model=BackfillStatus)
def backfill_status(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> BackfillStatus:
    job = backfill_job_repo.get_latest_for_user(db, user.id)
    if job is None:
        raise HTTPException(404, "No backfill has been run for this account yet")
    return _to_status(job)


@router.get("", response_model=list[RaceSummary])
def list_races(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[RaceSummary]:
    rows = race_repo.list_races_for_user(db, user.id)
    return [
        RaceSummary(
            activity_id=str(activity.id),
            name=activity.name,
            sport_type=activity.sport_type,
            distance_m=activity.distance_m,
            start_date=activity.start_date,
            heuristic_is_race=classification.heuristic_is_race,
            manual_override=classification.manual_override,
            distance_category=classification.distance_category,
        )
        for activity, classification in rows
    ]


@router.post("/{activity_id}/override")
def set_override(
    activity_id: uuid.UUID,
    body: ManualOverrideRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    activity = db.get(Activity, activity_id)
    if activity is None or activity.user_id != user.id:
        raise HTTPException(404, "No such activity for this account")

    classification = race_repo.get_classification(db, activity_id)
    if classification is None:
        raise HTTPException(404, "This activity has not been classified yet")

    updated = race_repo.set_manual_override(db, classification, body.is_race)
    return {"status": "updated", "is_race_effective": updated.is_race_effective}
