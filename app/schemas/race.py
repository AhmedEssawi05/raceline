"""Response/request DTOs for the races router — see app/schemas/auth.py for
why these exist instead of returning ORM objects directly as response
models.
"""

from datetime import datetime

from pydantic import BaseModel


class BackfillStatus(BaseModel):
    status: str
    pages_fetched: int
    activities_ingested: int
    activities_failed: int
    started_at: datetime | None
    finished_at: datetime | None
    last_error: str | None


class RaceSummary(BaseModel):
    activity_id: str
    name: str
    sport_type: str
    distance_m: float
    start_date: datetime
    heuristic_is_race: bool
    manual_override: bool | None
    distance_category: str | None


class ManualOverrideRequest(BaseModel):
    is_race: bool | None
