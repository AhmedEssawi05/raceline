"""CLI: populate `predictions` rows for the `riegel` method against every
currently-classified race with a known finish time.

WHAT: `python -m ml.predict_riegel [--athlete-ids ...]` walks every active
user's races (races per DESIGN.md's `is_race_effective` COALESCE) that have
a `race_details.finish_time_s`, treats each race's *reference performance*
as that athlete's most recent earlier race that also has a known finish
time, and writes one `riegel` prediction row per race that has a usable
reference. `athlete_ids=None` means every active user; a specific list is
the hook `evaluation/report.py` (Phase 5) uses to generate riegel
predictions for test-split athletes only, mirroring `ml/train.py`'s own
`athlete_ids` parameter.

WHY the reference performance is "most recent prior race with a known
finish time," not e.g. the athlete's personal best: recency reflects
current fitness, which is what Riegel's extrapolation assumes it's
measuring — a lifetime-best from years ago would misrepresent that. This is
a deliberate, simple, documented choice, not the only defensible one.

WHY a race with no qualifying prior race is skipped (no row written) rather
than written with a null prediction: unlike `strava_estimate`
(DESIGN.md's Explicit Flags item 1, where the *method itself* is always
unavailable and every classified race is expected to get an explanatory
null row), a missing Riegel reference is per-race and per-athlete —
skipping keeps this script idempotent without accumulating stale null rows
for races that later do get a usable reference (e.g. once an earlier race's
lazy detail fetch finally succeeds).

HOW re-runs behave: `prediction_repo.upsert_prediction` upserts on
`(activity_id, method, model_version_id)`, so re-running this script after
new races are backfilled, detail-fetched, or reclassified is safe — it
overwrites rather than duplicates.
"""

import uuid

from app.db import SessionLocal
from app.repositories import prediction_repo, race_repo, user_repo
from ml.registry import get_predictor


def run(athlete_ids: list[uuid.UUID] | None = None) -> int:
    predictor = get_predictor("riegel")
    written = 0
    db = SessionLocal()
    try:
        users = user_repo.list_active(db)
        if athlete_ids is not None:
            wanted = set(athlete_ids)
            users = [user for user in users if user.id in wanted]

        for user in users:
            races = race_repo.list_races_with_finish_time(db, user.id)
            for index in range(1, len(races)):  # index 0 has no prior race to reference
                activity, _detail = races[index]
                ref_activity, ref_detail = races[index - 1]

                predicted = predictor.predict(
                    [
                        {
                            "reference_distance_m": ref_activity.distance_m,
                            "reference_time_s": ref_detail.finish_time_s,
                            "target_distance_m": activity.distance_m,
                        }
                    ]
                )[0]

                if predicted is None:
                    notes = "reference performance data was incomplete"
                else:
                    notes = None
                prediction_repo.upsert_prediction(
                    db,
                    activity_id=activity.id,
                    method=predictor.method_name,
                    predicted_finish_time_s=predicted,
                    model_version_id=None,
                    notes=notes,
                )
                written += 1
        return written
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--athlete-ids",
        type=str,
        default=None,
        help="Comma-separated user UUIDs to restrict to (default: all active users).",
    )
    args = parser.parse_args()
    ids = (
        [uuid.UUID(id_.strip()) for id_ in args.athlete_ids.split(",")]
        if args.athlete_ids
        else None
    )

    count = run(athlete_ids=ids)
    print(f"Wrote {count} riegel prediction(s).")
