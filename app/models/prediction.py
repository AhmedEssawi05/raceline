"""Prediction and ModelVersion models.

WHAT: `Prediction` is one row per race per prediction method (`riegel` now;
`strava_estimate` and `trained_model` join it in later phases) — a
long/tidy table, not wide method columns, per DESIGN.md's reasoning: both
pandas and the eval SQL (Phase 5) want "join predictions across methods for
this race," and adding a 4th baseline later costs zero migration, just a
new `method` value.

WHY `ModelVersion` is created in this Phase-3 migration even though nothing
populates it until Phase 4's `ml/train.py`: `predictions.model_version_id`
is a nullable FK to it, and Postgres requires a referenced table to exist
before the FK constraint can be created. An unused-for-now table is the
standard, boring way to satisfy that — cheaper and less surprising than
deferring the FK constraint itself to a later migration.

WHY the unique constraint is `(activity_id, method, model_version_id)`, not
just `(activity_id, method)`: a `trained_model` row is scoped to *which*
trained model produced it — Phase 5 needs predictions from more than one
`eval_run`'s model version to coexist for the same race. `riegel`/
`strava_estimate` rows always have `model_version_id = NULL`.

CAVEAT this constraint doesn't fully cover: Postgres (like SQL generally)
treats NULL as distinct from NULL in a unique constraint, so it does *not*
by itself prevent two `riegel` rows for the same activity (both have
`model_version_id = NULL`). That's why `app/repositories/prediction_repo.py`
upserts via an explicit query-then-write (`WHERE model_version_id IS NULL`,
which Python's `== None` compiles to correctly), not a DB-level
`ON CONFLICT` — the constraint still earns its keep for `trained_model`
rows, where `model_version_id` is always set.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.json_type import JSONVariant

if TYPE_CHECKING:
    from app.models.activity import Activity


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    algorithm: Mapped[str] = mapped_column(nullable=False)
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    hyperparameters: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    training_athlete_ids: Mapped[list] = mapped_column(JSONVariant, nullable=False)
    artifact_path: Mapped[str] = mapped_column(nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(nullable=False)


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint(
            "activity_id", "method", "model_version_id", name="uq_predictions_activity_method_model"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    method: Mapped[str] = mapped_column(nullable=False)
    predicted_finish_time_s: Mapped[float | None] = mapped_column(nullable=True)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_versions.id"), nullable=True
    )
    predicted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    notes: Mapped[str | None] = mapped_column(nullable=True)

    activity: Mapped["Activity"] = relationship("Activity")
