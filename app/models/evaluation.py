"""AthleteSplit, EvalRun, EvalMetric — the persisted record of one Phase 5
evaluation run.

WHAT: `EvalRun` is one row per `evaluation.run_report` run. `AthleteSplit`
records each athlete's train/test assignment for that run, produced by
`evaluation.split.assign_splits` (a pure, unit-tested function) — this is
what makes the split "obviously correct and auditable" per DESIGN.md,
rather than an unverifiable in-memory shuffle nobody can check after the
fact. `EvalMetric` is one row per `(method, distance_category)` pair within
that run.

WHY split/run/metric are three separate tables rather than flattening the
split into `eval_runs` columns or the metrics into wide per-method columns:
each has a different cardinality relative to `eval_runs` (one split row per
athlete, one metric row per method/category) — flattening either would mean
a schema migration every time a distance category or prediction method is
added, exactly the anti-pattern DESIGN.md's "predictions is row-per-method,
not wide columns" reasoning already rejected elsewhere in this schema.

WHY `eval_metrics.distance_category` is nullable with `null = all
categories combined`, not a literal sentinel string like `"all"`: `NULL` is
the SQL-native "not restricted to a category" value — filterable/indexable
the same way any other nullable column is, without inventing a magic string
a caller could typo or that could collide with a real future category.

WHY `eval_runs.model_version_id` has no `ondelete` cascade (unlike most FKs
in this schema): deleting a `model_version` shouldn't silently erase the
evaluation history that was run against it — that would make past reported
accuracy numbers disappear right when someone might want to audit them.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_versions.id"), nullable=False
    )
    split_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    n_races_total: Mapped[int] = mapped_column(Integer, nullable=False)
    n_athletes_test: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(nullable=True)


class AthleteSplit(Base):
    __tablename__ = "athlete_splits"
    __table_args__ = (
        UniqueConstraint("eval_run_id", "user_id", name="uq_athlete_splits_run_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    eval_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    split: Mapped[str] = mapped_column(nullable=False)


class EvalMetric(Base):
    __tablename__ = "eval_metrics"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    eval_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    method: Mapped[str] = mapped_column(nullable=False)
    distance_category: Mapped[str | None] = mapped_column(nullable=True)
    n_races: Mapped[int] = mapped_column(Integer, nullable=False)
    mae_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    rmse_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    rmse_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
