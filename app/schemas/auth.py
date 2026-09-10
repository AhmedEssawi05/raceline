"""Response DTOs for the auth endpoints.

WHY a Pydantic schema here instead of returning the `User` ORM object
directly as `response_model`: a hand-picked field list means a field added
to `User` later for internal bookkeeping (e.g. `is_deleted`) can't leak into
an API response just because someone forgot to update this file — the
schema is the one place that has to be touched to expose something new.
"""

from datetime import datetime

from pydantic import BaseModel


class AccountStatus(BaseModel):
    connected: bool
    strava_athlete_id: int
    firstname: str | None
    lastname: str | None
    connected_since: datetime
