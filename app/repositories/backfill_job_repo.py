"""All DB access for a single backfill run's progress row (`backfill_jobs`),
called only from the races router (create/read) and worker/jobs/backfill.py
(the state-transition writes as the job runs).

WHY every mutation commits immediately, rather than batching writes across a
whole backfill: a caller polling `GET /races/backfill/status` is reading
this row from an entirely different process than the worker that's writing
it — a checkpoint that isn't committed the instant it happens isn't
observable, which defeats the point of `backfill_jobs` existing at all (see
app/models/backfill_job.py).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.backfill_job import BackfillJob


def create(db: Session, *, user_id: uuid.UUID) -> BackfillJob:
    job = BackfillJob(user_id=user_id, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def set_rq_job_id(db: Session, job: BackfillJob, rq_job_id: str) -> None:
    job.rq_job_id = rq_job_id
    db.commit()


def mark_running(db: Session, job: BackfillJob) -> None:
    job.status = "running"
    job.started_at = datetime.now(UTC)
    db.commit()


def record_page(db: Session, job: BackfillJob, *, pages_fetched: int) -> None:
    job.pages_fetched = pages_fetched
    db.commit()


def record_activity_ingested(db: Session, job: BackfillJob) -> None:
    job.activities_ingested += 1
    db.commit()


def record_activity_failed(db: Session, job: BackfillJob, *, error: str) -> None:
    job.activities_failed += 1
    job.last_error = error
    db.commit()


def mark_succeeded(db: Session, job: BackfillJob) -> None:
    job.status = "succeeded"
    job.finished_at = datetime.now(UTC)
    db.commit()


def mark_failed(db: Session, job: BackfillJob, *, error: str) -> None:
    job.status = "failed"
    job.last_error = error
    job.finished_at = datetime.now(UTC)
    db.commit()


def get_latest_for_user(db: Session, user_id: uuid.UUID) -> BackfillJob | None:
    return db.scalar(
        select(BackfillJob)
        .where(BackfillJob.user_id == user_id)
        .order_by(BackfillJob.created_at.desc())
        .limit(1)
    )
