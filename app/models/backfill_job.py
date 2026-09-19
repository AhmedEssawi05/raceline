"""BackfillJob — one row per backfill run, the DB-visible progress record for
an RQ ingestion job.

WHAT/WHY: per DESIGN.md's `backfill_jobs` rationale — Redis/RQ holds
transient job state, but isn't the source of truth for user-facing progress
across worker restarts and isn't easily queryable from a route or (Phase 6)
a Jinja template. One row per backfill run, updated at checkpoints by
worker/jobs/backfill.py via app/repositories/backfill_job_repo.py.

HOW `rq_job_id` is used: stored for optional live cross-reference against
Redis/RQ directly (`rq.job.Job.fetch(rq_job_id, connection=...)`) for
debugging a stuck job — nothing in the app reads it back yet, but it's
free to keep.

WHY `created_at` exists here even though DESIGN.md's `backfill_jobs` table
doesn't list it: "the latest backfill for this user" (the status-polling
read in app/repositories/backfill_job_repo.get_latest_for_user) needs a
monotonic creation timestamp to order by — `id` is a random UUID (no
creation-order meaning) and `started_at` is null until the worker actually
picks the job up, which would make a job's queued-but-not-yet-running state
briefly unfindable as "latest."
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class BackfillJob(Base):
    __tablename__ = "backfill_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rq_job_id: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(nullable=False, default="queued")
    pages_fetched: Mapped[int] = mapped_column(default=0, nullable=False)
    activities_ingested: Mapped[int] = mapped_column(default=0, nullable=False)
    activities_failed: Mapped[int] = mapped_column(default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(nullable=True)
