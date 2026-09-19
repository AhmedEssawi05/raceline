"""RQ job: training-load feature computation for one confirmed race.

WHAT: `compute_features(activity_id)` loads the race's athlete's full prior
activity history from the DB, maps it into the plain `PriorActivitySample`
shape `ingestion/feature_engineering.py` expects, and upserts one
`training_load_features` row.

WHY the ORM->plain-dataclass mapping happens here, not inside
feature_engineering.py: that module is deliberately ORM-free so its
windowing/threshold logic is unit-testable without a database (see its
docstring) — this job is the one place that bridges "what's in the DB" to
"what the pure function needs."

WHY `is_hard_effort` is computed per prior activity from
`ingestion/classifier.is_hard_effort`, using that activity's *own*
`is_race_effective` (not just its heuristic guess): an athlete's manual
override on a past activity should also change whether a later race treats
it as a "prior hard effort" — using the effective classification keeps that
one COALESCE (app/models/race.py) as the single source of truth for "was
this a race," instead of two classification-related values drifting apart.

WHY this reads the *entire* prior history rather than pre-filtering to a
fixed window in SQL: different features use different lookback windows
(ingestion/feature_engineering.py), so pulling the full ordered history once
and letting the pure function apply its own windows keeps that windowing
logic in one place instead of duplicated across SQL queries. At this
project's scale (one athlete's activity history) this is cheap; if history
size ever becomes a real concern, this query is the one to add a date
floor to.

HOW this is idempotent: `feature_repo.upsert_features` upserts on
`activity_id`, so re-running this job (e.g. after a manual reclassification
changes a prior activity's `is_race_effective`) overwrites the previous
feature row instead of duplicating it.
"""

import uuid

from app.db import SessionLocal
from app.models.activity import Activity
from app.repositories import activity_repo, feature_repo
from ingestion.classifier import is_hard_effort
from ingestion.feature_engineering import PriorActivitySample, compute_training_load_features


def compute_features(activity_id: str) -> None:
    db = SessionLocal()
    try:
        race = db.get(Activity, uuid.UUID(activity_id))
        if race is None:
            return

        prior = activity_repo.list_prior_activities(
            db, user_id=race.user_id, before=race.start_date
        )
        samples = [
            PriorActivitySample(
                start_date=a.start_date,
                distance_m=a.distance_m,
                moving_time_s=a.moving_time_s,
                sport_type=a.sport_type,
                is_hard_effort=is_hard_effort(
                    a.name,
                    is_race_effective=bool(a.classification and a.classification.is_race_effective),
                ),
            )
            for a in prior
        ]

        features = compute_training_load_features(
            race_start_date=race.start_date,
            race_avg_heart_rate=race.avg_heart_rate,
            race_avg_power_w=race.avg_power_w,
            prior_activities=samples,
        )
        feature_repo.upsert_features(db, activity=race, features=features)
    finally:
        db.close()
