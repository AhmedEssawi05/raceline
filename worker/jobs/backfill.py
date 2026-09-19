"""RQ job: full activity backfill for one user.

WHAT: `run_backfill(user_id, backfill_job_id)` pages through
`GET /athlete/activities` (app/strava/client.py), upserts every activity
into `activities`, classifies each one inline, and updates the
`backfill_jobs` row at each checkpoint — see app/models/backfill_job.py for
why that row, not Redis/RQ state, is the source of truth for progress.

WHY per-activity errors are caught and counted rather than raising: one
malformed payload (ingestion/activity_parser.py) must not abort an
otherwise-successful backfill of hundreds of activities — the spec's
resilience requirement, exercised by
tests/test_ingestion_error_handling.py. `activities_failed`/`last_error` on
the job row surface this without silently swallowing it.

WHY classification runs inline here rather than as its own enqueued job per
activity (a deviation from DESIGN.md's module list, which named a separate
`worker/jobs/classify_race.py`): classification
(ingestion/classifier.classify) is a pure, sub-millisecond, in-process
function with no I/O — enqueuing a separate RQ job per activity for it would
add real queue overhead (Redis round-trips, worker scheduling) for a
computation cheaper than the enqueue call itself. `fetch_race_detail` and
`compute_features`, which do real I/O and DB work per *race* (a small
subset of all activities), remain separate jobs, enqueued only for the
activities classification actually flags.

HOW pagination ends: Strava's `GET /athlete/activities` returns a
shorter-than-`per_page` (or empty) page once there's no more data — the
standard way this endpoint signals its end, used here as the loop's stop
condition instead of a fixed max-page count.
"""

import uuid

from app.db import SessionLocal
from app.models.backfill_job import BackfillJob
from app.models.user import User
from app.repositories import activity_repo, backfill_job_repo, race_repo
from app.strava import client as strava_client
from app.strava import oauth as strava_oauth
from ingestion.activity_parser import ActivityParseError, parse_activity
from ingestion.classifier import classify

_PER_PAGE = 100


def run_backfill(user_id: str, backfill_job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(BackfillJob, uuid.UUID(backfill_job_id))
        user = db.get(User, uuid.UUID(user_id))
        if job is None or user is None:
            return  # user disconnected/deleted while this job sat queued

        backfill_job_repo.mark_running(db, job)

        page = 1
        while True:
            access_token = strava_oauth.get_valid_access_token(db, user)
            raw_activities = strava_client.list_activities(
                access_token, page=page, per_page=_PER_PAGE
            )
            if not raw_activities:
                break

            for raw in raw_activities:
                _ingest_one(db, user_id=user.id, raw=raw, job=job)

            backfill_job_repo.record_page(db, job, pages_fetched=page)
            if len(raw_activities) < _PER_PAGE:
                break
            page += 1

        backfill_job_repo.mark_succeeded(db, job)
    except Exception as exc:  # noqa: BLE001 - the job must record failure, not just crash silently
        backfill_job_repo.mark_failed(db, job, error=str(exc))
        raise
    finally:
        db.close()


def _ingest_one(db, *, user_id: uuid.UUID, raw: dict, job: BackfillJob) -> None:
    try:
        fields = parse_activity(raw, user_id=user_id)
    except ActivityParseError as exc:
        backfill_job_repo.record_activity_failed(db, job, error=str(exc))
        return

    activity = activity_repo.upsert_activity(db, fields)
    backfill_job_repo.record_activity_ingested(db, job)

    result = classify(activity.name, activity.sport_type, activity.distance_m)
    race_repo.upsert_classification(
        db,
        activity=activity,
        heuristic_is_race=result.is_race,
        heuristic_matched_pattern=result.matched_pattern,
        distance_category=result.distance_category,
    )

    if result.is_race:
        from worker.jobs.fetch_race_detail import fetch_race_detail
        from worker.queue import queue

        queue.enqueue(fetch_race_detail, str(activity.id))
