"""Demo-mode data access: the athletes the public `/demo` pages show.

WHAT: `DEMO_ATHLETE_ID_BASE` marks which users are synthetic demo athletes
(see scripts/seed_demo.py). `list_demo_athletes` / `build_athlete_profile`
return, per demo athlete, their race history (the finish times the trained
model learned from) and a forward-looking predicted finish time for every
canonical distance, from both `riegel` and `trained_model`.

WHY the `/demo` pages are scoped to `strava_athlete_id >= DEMO_ATHLETE_ID_BASE`
rather than "any user": DESIGN.md's data-isolation rule keeps real athletes'
per-race data behind their own login. A public, no-login per-athlete view is
only safe for rows that are synthetic by construction.

WHY predictions are computed on the fly instead of read from `predictions`:
that table holds one row per *past* race. A demo viewer wants "what would
this athlete run at each distance," which has no matching activity row.
Riegel extrapolates from the athlete's most recent race; the trained model
reuses that race's training-load features with the target distance/category
swapped. Both are stated on the page so nobody mistakes the second for a
fully separate forecast of future training.

WHY each athlete is tagged `in_training_set`: the latest model is trained on
the train-split athletes only. Predictions for those athletes are in-sample
(the model has seen their results); only held-out athletes' predictions are a
fair test. The page says which one it is.
"""

import uuid
from dataclasses import dataclass, field

import joblib
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.evaluation import EvalRun
from app.models.features import TrainingLoadFeatures
from app.models.prediction import ModelVersion
from app.models.user import User
from app.repositories import evaluation_repo, race_repo
from ml.features import FEATURE_COLUMNS
from ml.riegel import RiegelPredictor

# Reserved, obviously-fake Strava athlete id range; real ids are far smaller.
DEMO_ATHLETE_ID_BASE = 900_000

# category -> combined swim+bike+run distance in meters. Matches
# ingestion/classifier.py's canonical buckets and scripts/seed_demo.py.
CANONICAL_DISTANCES_M = {
    "sprint": 750 + 20_000 + 5_000,
    "olympic": 1_500 + 40_000 + 10_000,
    "70.3": 1_900 + 90_000 + 21_097,
    "full": 3_800 + 180_000 + 42_195,
}


@dataclass
class HistoryRace:
    date: str
    name: str
    category: str | None
    finish_time_s: float


@dataclass
class DistancePrediction:
    category: str
    riegel_s: float | None
    trained_model_s: float | None


@dataclass
class AthleteProfile:
    user: User
    history: list[HistoryRace]
    predictions: list[DistancePrediction]
    in_training_set: bool | None  # None = no trained model available
    reference_race: HistoryRace | None = None
    notes: list[str] = field(default_factory=list)


def list_demo_athletes(db: Session) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .where(User.strava_athlete_id >= DEMO_ATHLETE_ID_BASE)
            .order_by(User.firstname, User.lastname)
        )
    )


def get_demo_athlete(db: Session, user_id: uuid.UUID) -> User | None:
    user = db.get(User, user_id)
    if user is None or user.strava_athlete_id < DEMO_ATHLETE_ID_BASE:
        return None
    return user


def _latest_model_version(db: Session) -> ModelVersion | None:
    eval_run: EvalRun | None = evaluation_repo.get_latest_eval_run(db)
    return db.get(ModelVersion, eval_run.model_version_id) if eval_run else None


def build_athlete_profile(db: Session, user: User) -> AthleteProfile:
    races = race_repo.list_races_with_finish_time(db, user.id)
    classifications = {
        activity.id: race_repo.get_classification(db, activity.id) for activity, _ in races
    }
    history = [
        HistoryRace(
            date=activity.start_date.strftime("%Y-%m-%d"),
            name=activity.name,
            category=classifications[activity.id].distance_category,
            finish_time_s=detail.finish_time_s,
        )
        for activity, detail in races
    ]
    profile = AthleteProfile(
        user=user, history=history, predictions=[], in_training_set=None
    )
    if not races:
        profile.notes.append("No race history, so there is nothing to predict from.")
        return profile

    ref_activity, ref_detail = races[-1]
    profile.reference_race = history[-1]

    model_version = _latest_model_version(db)
    predictor = None
    if model_version is not None:
        try:
            predictor = joblib.load(model_version.artifact_path)
            profile.in_training_set = str(user.id) in {
                str(i) for i in model_version.training_athlete_ids
            }
        except (OSError, ValueError):
            profile.notes.append("The trained model file could not be loaded.")
    else:
        profile.notes.append("No trained model yet. Run the demo setup script.")

    features = db.scalar(
        select(TrainingLoadFeatures).where(TrainingLoadFeatures.activity_id == ref_activity.id)
    )
    riegel = RiegelPredictor()

    for category, distance_m in CANONICAL_DISTANCES_M.items():
        riegel_s = riegel.predict(
            [
                {
                    "reference_distance_m": ref_activity.distance_m,
                    "reference_time_s": ref_detail.finish_time_s,
                    "target_distance_m": distance_m,
                }
            ]
        )[0]
        trained_s = None
        if predictor is not None and features is not None:
            record = {
                "target_distance_m": distance_m,
                "distance_category": category,
                "rolling_weekly_mileage_m": features.rolling_weekly_mileage_m,
                "rolling_weekly_duration_s": features.rolling_weekly_duration_s,
                "long_run_distance_4wk_m": features.long_run_distance_4wk_m,
                "days_since_last_hard_effort": features.days_since_last_hard_effort,
                "taper_indicator": features.taper_indicator,
                "avg_hr_available": features.avg_hr_available,
                "avg_power_available": features.avg_power_available,
                "feature_window_days": features.feature_window_days,
            }
            assert set(record) == set(FEATURE_COLUMNS)
            trained_s = predictor.predict([record])[0]
        profile.predictions.append(DistancePrediction(category, riegel_s, trained_s))
    return profile
