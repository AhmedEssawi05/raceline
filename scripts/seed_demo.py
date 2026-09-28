"""CLI: `python -m scripts.seed_demo` — populates the database with synthetic
athletes and race results so the public, no-login `/scoreboard` route (and
`python -m evaluation.run_report`, which it feeds) have something real to
show without a Strava account.

WHAT: inserts `User`/`Activity`/`RaceClassification`/`RaceDetail`/
`TrainingLoadFeatures` rows directly — the same tables the real Strava
ingestion pipeline (`worker/jobs/backfill.py` + `worker/jobs/compute_features.py`)
would write, just without going through Strava OAuth or the RQ worker at
all. Race names are run through the real `ingestion.classifier.classify`
heuristic (not hardcoded categories) so seeded data exercises the same
classification path real ingestion would.

WHY finish times are generated as `nominal_time_for_category * fitness_factor`,
where `fitness_factor` is derived from the same `rolling_weekly_mileage_m` /
`taper_indicator` values written to `training_load_features` (plus noise):
this gives `ml/train.py`'s gradient-boosting model an actual learnable
pattern (more training volume + a taper -> a faster relative finish) rather
than pure noise, so `python -m evaluation.run_report`'s comparison table
shows a `trained_model` that's doing something real, not memorizing labels.

WHY this only seeds base data and doesn't itself call `evaluation.run_report`:
keeps this script's job to exactly one thing (produce ingestable-looking
data), matching the rest of this repo's phase-separated CLIs (seed, then
train, then evaluate are still three separate, individually rerunnable
steps) — see the README's "Demo Mode" section for the exact three-command
sequence.

Safe to rerun: `--reset` deletes every user this script previously created
(matched by `strava_athlete_id` in the reserved demo range below) before
reseeding, so repeated runs don't pile up duplicate athletes.
"""

import argparse
import random
from datetime import UTC, datetime, timedelta

from app.db import SessionLocal
from app.models.activity import Activity
from app.models.features import TrainingLoadFeatures
from app.models.race import RaceClassification, RaceDetail
from app.models.user import User
from ingestion.classifier import classify

# Reserved, obviously-fake Strava athlete id range so this script's rows are
# always identifiable and safe to delete/reseed without touching any real
# ingested user (real Strava athlete ids are far smaller integers).
DEMO_ATHLETE_ID_BASE = 900_000

ATHLETE_NAMES = [
    ("Jordan", "Reyes"),
    ("Priya", "Nair"),
    ("Sam", "Okafor"),
    ("Mika", "Lindqvist"),
    ("Diego", "Alvarez"),
    ("Anh", "Tran"),
    ("Casey", "Novak"),
    ("Ruth", "Mensah"),
]

CITIES = [
    "Austin",
    "Boulder",
    "Chattanooga",
    "Tempe",
    "Muncie",
    "Lake Placid",
    "Coeur d'Alene",
    "Tulsa",
]

# category -> (nominal finish time at fitness_factor=1.0, combined swim+bike+run
# distance in meters). Distances match ingestion/classifier.py's own canonical
# triathlon-distance buckets so the seeded distance_m round-trips through the
# same classifier the real pipeline uses.
CATEGORY_SPEC = {
    "sprint": (5_400, 750 + 20_000 + 5_000),
    "olympic": (10_800, 1_500 + 40_000 + 10_000),
    "70.3": (21_600, 1_900 + 90_000 + 21_097),
    "full": (43_200, 3_800 + 180_000 + 42_195),
}
RACE_NAME_TEMPLATE = {
    "sprint": "{city} Sprint Triathlon",
    "olympic": "{city} Olympic Triathlon",
    "70.3": "IRONMAN 70.3 {city}",
    "full": "IRONMAN {city}",
}


def _delete_existing_demo_users(db) -> int:
    demo_users = (
        db.query(User)
        .filter(User.strava_athlete_id >= DEMO_ATHLETE_ID_BASE)
        .all()
    )
    for user in demo_users:
        db.delete(user)  # cascades to activities/classifications/details/features
    db.commit()
    return len(demo_users)


def seed(db, n_athletes: int = 8, seed: int = 7) -> tuple[int, int]:
    rng = random.Random(seed)
    total_races = 0

    for i in range(n_athletes):
        firstname, lastname = ATHLETE_NAMES[i % len(ATHLETE_NAMES)]
        user = User(
            strava_athlete_id=DEMO_ATHLETE_ID_BASE + i, firstname=firstname, lastname=lastname
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # This athlete's typical training volume, in meters/week — the main
        # driver of both the seeded rolling-mileage feature and how fast their
        # races come out (see module docstring).
        base_weekly_mileage_m = rng.uniform(25_000, 70_000)

        n_races = rng.randint(4, 6)
        race_date = datetime(2024, 6, 1, tzinfo=UTC) + timedelta(days=rng.randint(0, 120))

        for r in range(n_races):
            category = rng.choice(list(CATEGORY_SPEC))
            nominal_time_s, nominal_distance_m = CATEGORY_SPEC[category]
            distance_m = nominal_distance_m * rng.uniform(0.98, 1.02)
            city = rng.choice(CITIES)
            name = RACE_NAME_TEMPLATE[category].format(city=city)

            weekly_mileage_m = max(10_000, base_weekly_mileage_m + rng.uniform(-8_000, 8_000))
            taper_indicator = rng.random() < 0.6

            fitness_factor = 1.15 - 0.003 * (weekly_mileage_m / 1_000)
            fitness_factor = max(0.85, min(1.15, fitness_factor))
            taper_bonus = -0.02 if taper_indicator else 0.0
            noise = rng.gauss(0, 0.03)
            finish_time_s = round(nominal_time_s * (fitness_factor + taper_bonus + noise))

            result = classify(name, "Triathlon", distance_m)

            activity = Activity(
                user_id=user.id,
                strava_activity_id=1_000_000 + i * 100 + r,
                name=name,
                sport_type="Triathlon",
                distance_m=distance_m,
                moving_time_s=finish_time_s,
                elapsed_time_s=finish_time_s + rng.randint(30, 180),
                start_date=race_date,
                raw_payload={},
            )
            db.add(activity)
            db.commit()
            db.refresh(activity)

            db.add(
                RaceClassification(
                    activity_id=activity.id,
                    heuristic_is_race=result.is_race,
                    heuristic_matched_pattern=result.matched_pattern,
                    distance_category=result.distance_category,
                )
            )
            db.add(RaceDetail(activity_id=activity.id, finish_time_s=finish_time_s))
            db.add(
                TrainingLoadFeatures(
                    activity_id=activity.id,
                    rolling_weekly_mileage_m=weekly_mileage_m,
                    rolling_weekly_duration_s=weekly_mileage_m / 3.0,
                    long_run_distance_4wk_m=weekly_mileage_m * rng.uniform(0.15, 0.25),
                    days_since_last_hard_effort=rng.randint(3, 14),
                    taper_indicator=taper_indicator,
                    avg_hr_available=True,
                    avg_power_available=False,
                    feature_window_days=28,
                )
            )
            db.commit()
            total_races += 1

            race_date = race_date + timedelta(days=rng.randint(60, 150))

    return n_athletes, total_races


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--athletes", type=int, default=8, help="Number of demo athletes.")
    parser.add_argument("--seed", type=int, default=7, help="RNG seed (deterministic output).")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete any previously seeded demo athletes (strava_athlete_id >= "
        f"{DEMO_ATHLETE_ID_BASE}) before seeding.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.reset:
            removed = _delete_existing_demo_users(db)
            print(f"Removed {removed} previously seeded demo athlete(s).")

        n_athletes, n_races = seed(db, n_athletes=args.athletes, seed=args.seed)
        print(
            f"Seeded {n_athletes} demo athlete(s) with {n_races} classified race(s), "
            "each with a known finish time and computed training-load features."
        )
        print("Next: docker compose exec api python -m evaluation.run_report")
    finally:
        db.close()
