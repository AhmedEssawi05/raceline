"""Activity model — one row per synced Strava activity, race or not.

WHAT: the bulk-ingestion table. Every activity Strava returns for a user
during a backfill lands here regardless of whether it's later classified as
a race — see DESIGN.md's "activities and races share one table" decision.
`RaceClassification`/`RaceDetail`/`TrainingLoadFeatures` (app/models/race.py,
app/models/features.py) are 1:1 subsets keyed off this table's `id`.

WHY `raw_payload` stores the full Strava JSON alongside the extracted
columns: reprocessing (a future feature needs a field this schema didn't
originally extract) means replaying `raw_payload` through a new parser
version, not re-fetching from Strava and spending rate-limit budget again.

WHY `avg_heart_rate`/`avg_power_w` are nullable with no default-to-zero:
Strava simply omits these fields for activities with no HR strap or power
meter. Coercing that to `0` would misrepresent "no data" as "zero effort,"
which would poison any model later trained on this column —
`training_load_features` carries explicit `avg_hr_available`/
`avg_power_available` flags precisely so a missing measurement stays a
legible signal (app/models/features.py).

WHY `ingestion_error` sits next to a still-created row instead of the row
being skipped: ingestion/activity_parser.py can produce a usable row from a
*partially* malformed payload (e.g. Strava omits `total_elevation_gain` for
some indoor/manual entries) — the row still deserves to exist, with the
parser's degraded-field list recorded here for later debugging. Only a
payload unusable for the unique constraint or date ordering (missing `id` or
`start_date`) is rejected outright — see activity_parser.py for the exact
contract this column reflects.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.json_type import JSONVariant

if TYPE_CHECKING:
    from app.models.features import TrainingLoadFeatures
    from app.models.race import RaceClassification, RaceDetail
    from app.models.user import User


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint("user_id", "strava_activity_id", name="uq_activities_user_strava_id"),
        Index("ix_activities_user_id_start_date", "user_id", "start_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    strava_activity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(nullable=False)
    sport_type: Mapped[str] = mapped_column(nullable=False)
    distance_m: Mapped[float] = mapped_column(nullable=False)
    moving_time_s: Mapped[int] = mapped_column(nullable=False)
    elapsed_time_s: Mapped[int] = mapped_column(nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_elevation_gain_m: Mapped[float | None] = mapped_column(nullable=True)
    avg_heart_rate: Mapped[float | None] = mapped_column(nullable=True)
    avg_power_w: Mapped[float | None] = mapped_column(nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONVariant, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    ingestion_error: Mapped[str | None] = mapped_column(nullable=True)

    user: Mapped["User"] = relationship("User")
    classification: Mapped["RaceClassification | None"] = relationship(
        "RaceClassification", back_populates="activity", uselist=False, cascade="all, delete-orphan"
    )
    detail: Mapped["RaceDetail | None"] = relationship(
        "RaceDetail", back_populates="activity", uselist=False, cascade="all, delete-orphan"
    )
    features: Mapped["TrainingLoadFeatures | None"] = relationship(
        "TrainingLoadFeatures",
        back_populates="activity",
        uselist=False,
        cascade="all, delete-orphan",
    )
