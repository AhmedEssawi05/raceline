"""RQ job: lazy detail fetch for a single confirmed race.

WHAT: `fetch_race_detail(activity_id)` calls `GET /activities/{id}` (full
detail, including laps) for one race and writes the `race_details` row.

WHY this is a separate, per-race job rather than folded into the bulk
backfill loop: DESIGN.md's `race_details` is "1:1, only populated when
is_race_effective = true" precisely to keep this heavier, second API call
off the hot bulk-ingestion path — most synced activities are not races, so
fetching detail for all of them would spend rate-limit budget
(app/strava/rate_limit.py) on data nothing will ever read.

WHY failures are recorded on the row (`fetch_error`) rather than raised:
a detail fetch can fail independently of the activity already being
successfully ingested (rate limit, a transient 5xx, a since-deleted Strava
activity) — recording the error makes it retryable later without re-running
the whole backfill, which is exactly what `race_details.fetch_error` is for.

HOW `splits` maps to Strava's response: stored as the raw `laps` array —
`race_details.splits` is deliberately JSONB (see DESIGN.md) since lap
structure varies by sport/distance and nothing in this project queries
inside it, only displays it.

WHAT'S NOT implemented: `elevation_profile` needs Strava's separate streams
endpoint (`GET /activities/{id}/streams`), which is out of Phase 2's scope
per the build order — it's always written as `None` here, the same
"structurally present, not yet populated" pattern DESIGN.md uses for
`race_details.weather`.
"""

import uuid

from app.db import SessionLocal
from app.models.activity import Activity
from app.repositories import race_repo
from app.strava import client as strava_client
from app.strava import oauth as strava_oauth


def fetch_race_detail(activity_id: str) -> None:
    db = SessionLocal()
    try:
        activity = db.get(Activity, uuid.UUID(activity_id))
        if activity is None:
            return

        try:
            access_token = strava_oauth.get_valid_access_token(db, activity.user)
            detail = strava_client.get_activity_detail(access_token, activity.strava_activity_id)
        except Exception as exc:  # noqa: BLE001 - record on the row, don't crash the worker
            race_repo.record_detail_fetch_error(db, activity, error=str(exc))
            return

        race_repo.upsert_detail(
            db,
            activity=activity,
            splits=detail.get("laps"),
            elevation_profile=None,
            finish_time_s=detail.get("elapsed_time"),
        )

        from worker.jobs.compute_features import compute_features
        from worker.queue import queue

        queue.enqueue(compute_features, str(activity.id))
    finally:
        db.close()
