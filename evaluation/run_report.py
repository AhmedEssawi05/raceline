"""CLI: `python -m evaluation.run_report [--seed N]` — runs the full Phase 5
evaluation pipeline (`evaluation/report.py`) and prints the three-method
comparison table with a small-N caveat printed inline per row.

WHY the small-N caveat is printed per-row, not just once at the top:
DESIGN.md's `eval_metrics.n_races` note ("required for inline small-N
flagging") means the caveat has to travel with the specific number it
qualifies — a global disclaimer wouldn't tell a reader *which* rows in a
mixed table (some with 8 test races, some with 1) are the ones to treat
skeptically.

HOW `SMALL_N_THRESHOLD` was chosen: a judgment call, not a statistical
derivation — below 5 test races, a single unusually good or bad prediction
swings the mean enough that the metric shouldn't be read as "this method's
typical accuracy." Flagged here the same way this project flags its other
non-derived, documented assumptions (see DESIGN.md's Explicit Flags list).
"""

import argparse

from app.db import SessionLocal
from app.models.evaluation import EvalRun
from app.repositories import evaluation_repo
from evaluation.report import DEFAULT_SEED, run_report

SMALL_N_THRESHOLD = 5


def _format(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "n/a"


def _print_report(eval_run_id) -> None:
    db = SessionLocal()
    try:
        eval_run = db.get(EvalRun, eval_run_id)
        metrics = evaluation_repo.list_metrics_for_run(db, eval_run_id)

        print(
            f"Eval run {eval_run.id} — seed={eval_run.split_seed}, "
            f"{eval_run.n_athletes_test} test athlete(s), "
            f"{eval_run.n_races_total} test race(s)"
        )
        header = (
            f"{'method':<16}{'category':<12}{'n':>4}"
            f"{'MAE(min)':>10}{'RMSE(min)':>11}{'MAE(%)':>9}{'RMSE(%)':>9}"
        )
        print(header)
        print("-" * len(header))

        for metric in sorted(metrics, key=lambda m: (m.method, m.distance_category or "")):
            category = metric.distance_category or "all"
            caveat = " (small N)" if 0 < metric.n_races < SMALL_N_THRESHOLD else ""
            print(
                f"{metric.method:<16}{category:<12}{metric.n_races:>4}"
                f"{_format(metric.mae_minutes):>10}{_format(metric.rmse_minutes):>11}"
                f"{_format(metric.mae_pct):>9}{_format(metric.rmse_pct):>9}{caveat}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    eval_run_id = run_report(seed=args.seed)
    _print_report(eval_run_id)
