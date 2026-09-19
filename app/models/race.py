"""Race classification and race detail models — 1:1 subsets of `activities`.

WHAT: `RaceClassification` exists for every activity the heuristic has
looked at — created inline for *every* ingested activity during backfill
(see worker/jobs/backfill.py), not only for ones it thinks are races.
`RaceDetail` exists only once a race is confirmed effective and its lazy
detail fetch has run (worker/jobs/fetch_race_detail.py).

WHY `heuristic_is_race` and `manual_override` are two separate columns
(one never-null, one nullable) rather than one collapsed flag, per
DESIGN.md: the heuristic's original verdict has to stay legible even after
a human overrides it — that's what makes a wrong heuristic call debuggable
later ("why did the classifier miss this?") instead of silently lost the
moment someone corrects it. `is_race_effective` is a DB-generated column
(`COALESCE(manual_override, heuristic_is_race)`) so both the ORM and raw SQL
filter/index on "the classification that actually counts" without
re-deriving that COALESCE in every query site.

WHY `RaceDetail.weather` is JSONB and always null in Phase 2 (see
DESIGN.md's Explicit Flags item 3): a future weather API integration keyed
on (date, location) can fill this in later without a schema migration —
nothing in this phase's ingestion ever writes anything but null here.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Computed, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.json_type import JSONVariant

if TYPE_CHECKING:
    from app.models.activity import Activity


class RaceClassification(Base):
    __tablename__ = "race_classifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    heuristic_is_race: Mapped[bool] = mapped_column(nullable=False)
    heuristic_matched_pattern: Mapped[str | None] = mapped_column(nullable=True)
    manual_override: Mapped[bool | None] = mapped_column(nullable=True)
    distance_category: Mapped[str | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    is_race_effective: Mapped[bool] = mapped_column(
        Boolean,
        Computed("COALESCE(manual_override, heuristic_is_race)", persisted=True),
        nullable=False,
        index=True,
    )

    activity: Mapped["Activity"] = relationship("Activity", back_populates="classification")


class RaceDetail(Base):
    __tablename__ = "race_details"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    splits: Mapped[dict | list | None] = mapped_column(JSONVariant, nullable=True)
    elevation_profile: Mapped[dict | list | None] = mapped_column(JSONVariant, nullable=True)
    weather: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    finish_time_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    fetch_error: Mapped[str | None] = mapped_column(nullable=True)

    activity: Mapped["Activity"] = relationship("Activity", back_populates="detail")
