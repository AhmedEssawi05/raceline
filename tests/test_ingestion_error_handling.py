"""Malformed-activity resilience: the parser layer (unit) and the full
backfill job (integration against the in-memory test DB) must both survive
a bad payload without losing the rest of a user's data.

WHAT (integration tests): drives the real `run_backfill` job function,
mocking only what would otherwise need a live Strava account
(`app.strava.oauth.get_valid_access_token`, `app.strava.client.list_activities`)
or live Redis (`worker.jobs.backfill.SessionLocal` swapped to the test DB
session; `worker.queue.queue.enqueue` no-op'd since a matched race would
otherwise try to enqueue a real detail-fetch job).
"""

from unittest.mock import patch

import pytest

from app.models.backfill_job import BackfillJob
from app.models.user import User
from app.repositories import activity_repo
from ingestion.activity_parser import ActivityParseError, parse_activity
from worker.jobs.backfill import run_backfill

USER_ID = "11111111-1111-1111-1111-111111111111"


def test_missing_id_is_rejected_entirely() -> None:
    payload = {"name": "No id here", "start_date": "2026-06-01T00:00:00Z"}
    with pytest.raises(ActivityParseError):
        parse_activity(payload, user_id=USER_ID)


def test_missing_start_date_is_rejected_entirely() -> None:
    with pytest.raises(ActivityParseError):
        parse_activity({"id": 1, "name": "No date here"}, user_id=USER_ID)


def test_missing_optional_fields_degrade_with_a_recorded_note() -> None:
    fields = parse_activity(
        {"id": 2, "start_date": "2026-06-01T00:00:00Z"},  # no name, sport_type, distance, ...
        user_id=USER_ID,
    )

    assert fields["name"] == "Untitled activity"
    assert fields["sport_type"] == "Unknown"
    assert fields["distance_m"] == 0.0
    assert fields["ingestion_error"] is not None
    assert "name" in fields["ingestion_error"]
    assert "distance" in fields["ingestion_error"]


GOOD_ACTIVITY = {
    "id": 111,
    "name": "Easy morning run",
    "sport_type": "Run",
    "distance": 8000.0,
    "moving_time": 2400,
    "elapsed_time": 2500,
    "start_date": "2026-06-01T13:00:00Z",
}

UNUSABLE_ACTIVITY = {
    # no "id" -- the one case activity_parser can't degrade around.
    "name": "Corrupted payload",
    "sport_type": "Run",
    "start_date": "2026-06-02T13:00:00Z",
}

PARTIALLY_MALFORMED_ACTIVITY = {
    "id": 222,
    "name": "IRONMAN 70.3 Austin",
    "sport_type": "Run",
    # "distance" missing -- degrades to 0.0 with a recorded note, row is kept.
    "moving_time": 14_000,
    "elapsed_time": 14_200,
    "start_date": "2026-06-08T13:00:00Z",
}


def _seed_user_and_job(db_session, strava_athlete_id: int) -> tuple[User, BackfillJob]:
    user = User(strava_athlete_id=strava_athlete_id)
    db_session.add(user)
    db_session.commit()
    job = BackfillJob(user_id=user.id, status="queued")
    db_session.add(job)
    db_session.commit()
    return user, job


def test_backfill_survives_one_totally_unusable_activity(db_session) -> None:
    user, job = _seed_user_and_job(db_session, strava_athlete_id=1)
    pages = [[GOOD_ACTIVITY, UNUSABLE_ACTIVITY]]

    with (
        patch("worker.jobs.backfill.SessionLocal", lambda: db_session),
        # the job's `finally: db.close()` must not close the shared test session
        patch.object(db_session, "close"),
        patch("app.strava.oauth.get_valid_access_token", return_value="fake-token"),
        patch("app.strava.client.list_activities", side_effect=lambda *a, **k: pages.pop(0)),
        patch("worker.queue.queue.enqueue"),
    ):
        run_backfill(str(user.id), str(job.id))

    assert job.status == "succeeded"
    assert job.activities_ingested == 1
    assert job.activities_failed == 1
    assert job.last_error is not None and "id" in job.last_error

    stored = activity_repo.list_for_user(db_session, user.id)
    assert len(stored) == 1
    assert stored[0].strava_activity_id == 111


def test_backfill_keeps_a_row_for_a_partially_malformed_but_usable_activity(db_session) -> None:
    user, job = _seed_user_and_job(db_session, strava_athlete_id=2)
    pages = [[PARTIALLY_MALFORMED_ACTIVITY]]

    with (
        patch("worker.jobs.backfill.SessionLocal", lambda: db_session),
        # the job's `finally: db.close()` must not close the shared test session
        patch.object(db_session, "close"),
        patch("app.strava.oauth.get_valid_access_token", return_value="fake-token"),
        patch("app.strava.client.list_activities", side_effect=lambda *a, **k: pages.pop(0)),
        patch("worker.queue.queue.enqueue"),
    ):
        run_backfill(str(user.id), str(job.id))

    assert job.activities_ingested == 1
    assert job.activities_failed == 0

    stored = activity_repo.list_for_user(db_session, user.id)
    assert len(stored) == 1
    assert stored[0].distance_m == 0.0
    assert stored[0].ingestion_error is not None and "distance" in stored[0].ingestion_error
