"""Raw Strava activity JSON -> `Activity` row fields. Pure, no DB/network.

WHAT: `parse_activity(raw, user_id=...)` turns one element of Strava's
`GET /athlete/activities` response into the kwargs dict
`app/repositories/activity_repo.upsert_activity` needs to build/update an
`Activity` row.

WHY only `id` and `start_date` can abort ingestion of an activity entirely
(raising `ActivityParseError`), while every other field degrades to a
default with a note in `ingestion_error`: `id` is load-bearing for the
`(user_id, strava_activity_id)` uniqueness constraint, and `start_date`
drives every downstream date-ordered query (rolling windows, "prior
activities," the race list). Without either, there is no sensible row to
store. Everything else (a missing `name`, a non-numeric `distance`) can be
defaulted and flagged — the spec's requirement that one malformed activity
must not crash a whole-user backfill (see
tests/test_ingestion_error_handling.py) is best satisfied by keeping as much
of a partially-bad payload as possible, not by discarding it.

HOW Strava's `start_date` is parsed: it's an ISO-8601 UTC string ending in
`Z` (e.g. `"2026-06-01T13:00:00Z"`), which Python's `datetime.fromisoformat`
only accepts once `Z` is swapped for the explicit `+00:00` offset — that
swap, not a full RFC-3339 parser, is all this needs since Strava's format is
fixed.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ActivityParseError(Exception):
    message: str
    strava_activity_id: object | None = None

    def __str__(self) -> str:
        return self.message


@dataclass
class _FieldErrors:
    notes: list[str] = field(default_factory=list)

    def record(self, field_name: str) -> None:
        self.notes.append(f"missing/invalid '{field_name}'")

    def as_ingestion_error(self) -> str | None:
        return "; ".join(self.notes) if self.notes else None


def _parse_start_date(raw_value: object) -> datetime | None:
    if not isinstance(raw_value, str) or not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_activity(raw: dict, *, user_id: uuid.UUID) -> dict:
    strava_activity_id = raw.get("id")
    if strava_activity_id is None:
        raise ActivityParseError("activity payload has no 'id' — cannot store without one")

    start_date = _parse_start_date(raw.get("start_date"))
    if start_date is None:
        raise ActivityParseError(
            "activity is missing a usable 'start_date' — cannot store without one",
            strava_activity_id,
        )

    errors = _FieldErrors()

    name = raw.get("name")
    if not isinstance(name, str) or not name:
        errors.record("name")
        name = "Untitled activity"

    sport_type = raw.get("sport_type")
    if not isinstance(sport_type, str) or not sport_type:
        errors.record("sport_type")
        sport_type = "Unknown"

    def _optional_float(field_name: str) -> float | None:
        value = raw.get(field_name)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            errors.record(field_name)
            return None

    def _required_numeric(field_name: str, cast: type, default: float | int) -> float | int:
        value = raw.get(field_name)
        try:
            return cast(value)
        except (TypeError, ValueError):
            errors.record(field_name)
            return default

    return {
        "user_id": user_id,
        "strava_activity_id": int(strava_activity_id),
        "name": name,
        "sport_type": sport_type,
        "distance_m": _required_numeric("distance", float, 0.0),
        "moving_time_s": _required_numeric("moving_time", int, 0),
        "elapsed_time_s": _required_numeric("elapsed_time", int, 0),
        "start_date": start_date,
        "total_elevation_gain_m": _optional_float("total_elevation_gain"),
        "avg_heart_rate": _optional_float("average_heartrate"),
        "avg_power_w": _optional_float("average_watts"),
        "raw_payload": raw,
        "ingestion_error": errors.as_ingestion_error(),
    }
