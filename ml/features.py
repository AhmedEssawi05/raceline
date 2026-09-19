"""DB rows -> pandas DataFrame, the trained model's feature matrix.

WHAT: `build_feature_matrix(db, athlete_ids=None)` returns one row per race
that has both computed training-load features and a known finish time —
`app/repositories/feature_repo.list_races_with_features` is where that join
lives; this module's job is turning those ORM rows into the flat DataFrame
`ml/gradient_boosting.py` and `ml/train.py` consume. Optional `athlete_ids`
restricts to a specific set of users, which is the hook Phase 5's evaluation
will use to build a feature matrix from train-split athletes only, without
this module needing to know anything about splits itself.

WHY a race with no computed features or no known finish time is excluded
entirely, rather than included with nulls: `training_load_features`/
`race_details.finish_time_s` not existing yet means the ingestion pipeline
hasn't finished with this race (compute_features.py hasn't run, or the
detail fetch failed) — it isn't a training example with missing values, per
DESIGN.md's explicit-null contract, it's not a training example at all yet.

WHY `activity_id`/`user_id`/`finish_time_s` ride along as ordinary columns
instead of being split out immediately: `ml/train.py` needs all three
(the identifier to key predictions on, the athlete id for the
`training_athlete_ids` audit trail, and the label to fit against) alongside
the feature columns — keeping one DataFrame with a documented column list
(`FEATURE_COLUMNS` below) is what makes "which columns are identifiers, the
label, or actual model input" legible in one place, rather than three
parallel arrays a caller has to keep in sync by hand.

Feature columns (`FEATURE_COLUMNS`): `target_distance_m` (the race's own
distance — no triathlon finish-time model can do without it) and
`distance_category` (categorical text; `ml/gradient_boosting.py` owns
encoding it), plus the exact `training_load_features` column set
(app/models/features.py): `rolling_weekly_mileage_m`,
`rolling_weekly_duration_s`, `long_run_distance_4wk_m`,
`days_since_last_hard_effort`, `taper_indicator`, `avg_hr_available`,
`avg_power_available`, `feature_window_days`.
"""

import uuid

import pandas as pd
from sqlalchemy.orm import Session

from app.repositories.feature_repo import list_races_with_features

FEATURE_SCHEMA_VERSION = "v1"

ID_COLUMNS = ["activity_id", "user_id"]
TARGET_COLUMN = "finish_time_s"
FEATURE_COLUMNS = [
    "target_distance_m",
    "distance_category",
    "rolling_weekly_mileage_m",
    "rolling_weekly_duration_s",
    "long_run_distance_4wk_m",
    "days_since_last_hard_effort",
    "taper_indicator",
    "avg_hr_available",
    "avg_power_available",
    "feature_window_days",
]
ALL_COLUMNS = ID_COLUMNS + FEATURE_COLUMNS + [TARGET_COLUMN]


def build_feature_matrix(db: Session, athlete_ids: list[uuid.UUID] | None = None) -> pd.DataFrame:
    rows = list_races_with_features(db, athlete_ids)
    records = [
        {
            "activity_id": str(activity.id),
            "user_id": str(activity.user_id),
            "target_distance_m": activity.distance_m,
            "distance_category": classification.distance_category,
            "rolling_weekly_mileage_m": features.rolling_weekly_mileage_m,
            "rolling_weekly_duration_s": features.rolling_weekly_duration_s,
            "long_run_distance_4wk_m": features.long_run_distance_4wk_m,
            "days_since_last_hard_effort": features.days_since_last_hard_effort,
            "taper_indicator": features.taper_indicator,
            "avg_hr_available": features.avg_hr_available,
            "avg_power_available": features.avg_power_available,
            "feature_window_days": features.feature_window_days,
            "finish_time_s": detail.finish_time_s,
        }
        for activity, classification, features, detail in rows
    ]
    return pd.DataFrame.from_records(records, columns=ALL_COLUMNS)
