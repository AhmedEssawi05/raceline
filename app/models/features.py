"""TrainingLoadFeatures — one row per race, the model's full input contract.

WHAT: precomputed rolling-training-load features for one confirmed race,
written by worker/jobs/compute_features.py from the pure functions in
ingestion/feature_engineering.py.

WHY a wide explicit-column table, not EAV or a single JSON blob, per
DESIGN.md: the feature set is small and fixed, so a wide table (a) is
queryable/indexable for eval and debugging, (b) loads directly into a
pandas/sklearn feature matrix via `pd.read_sql` (Phase 4's `ml/features.py`),
and (c) *documents* the model's input contract in the schema itself —
important for a project whose deliverable is meant to be legible to a
reviewer, not just to the model. `extra_features` is the one JSONB escape
hatch for experimental columns added between migrations.

WHY `avg_hr_available`/`avg_power_available` are non-nullable booleans next
to features that are themselves nullable: they are the model's
missing-indicator features — Phase 4's trained model needs to know *that*
a measurement is missing, not just see a null and guess, so the flag itself
must always be knowable even when the value it describes isn't.

WHY `feature_window_days` is stored per-row rather than assumed constant:
it records the actual lookback used for *this* computation, so a later
change to the default window (ingestion/feature_engineering.py) doesn't
silently make old rows ambiguous about what they measured — reproducibility
per DESIGN.md.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.json_type import JSONVariant

if TYPE_CHECKING:
    from app.models.activity import Activity


class TrainingLoadFeatures(Base):
    __tablename__ = "training_load_features"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    rolling_weekly_mileage_m: Mapped[float | None] = mapped_column(nullable=True)
    rolling_weekly_duration_s: Mapped[float | None] = mapped_column(nullable=True)
    long_run_distance_4wk_m: Mapped[float | None] = mapped_column(nullable=True)
    days_since_last_hard_effort: Mapped[int | None] = mapped_column(Integer, nullable=True)
    taper_indicator: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    avg_hr_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    avg_power_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    feature_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    extra_features: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    activity: Mapped["Activity"] = relationship("Activity", back_populates="features")
