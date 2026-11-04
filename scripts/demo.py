"""CLI: `python -m scripts.demo` — one command that builds the whole demo.

WHAT: reseeds the synthetic demo athletes (`scripts.seed_demo`, deterministic
via its fixed seed) and runs `evaluation.run_report`, which trains the model
and writes the predictions and scoreboard. Afterwards `/demo` and
`/scoreboard` have data, with no Strava account or ingestion worker involved.

WHY a wrapper instead of README's three separate commands: a live demo should
be one step. The underlying scripts stay independently runnable.

Requires the schema to exist first (`alembic upgrade head`).
"""

from app.db import SessionLocal
from evaluation.report import run_report
from scripts.seed_demo import _delete_existing_demo_users, seed

if __name__ == "__main__":
    db = SessionLocal()
    try:
        removed = _delete_existing_demo_users(db)
        n_athletes, n_races = seed(db)
    finally:
        db.close()
    print(f"Seeded {n_athletes} demo athlete(s), {n_races} race(s) (replaced {removed}).")
    print(f"Evaluation run {run_report()} written.")
    print("Open http://localhost:8000/demo")
