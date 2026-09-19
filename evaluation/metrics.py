"""MAE/RMSE for finish-time predictions, in minutes and as a percentage of
actual finish time — pure function, no DB.

WHAT: `compute_metrics(pairs)` takes a list of
`(actual_finish_time_s, predicted_finish_time_s | None)` tuples for one
method (optionally pre-filtered to one distance category by the caller) and
returns `{n_races, mae_minutes, rmse_minutes, mae_pct, rmse_pct}` —
directly the column set `eval_metrics` needs.

WHY both minutes and percent-of-finish-time: DESIGN.md wants both because
either framing alone is misleading here — a 2-minute error on a sprint
triathlon (roughly 1-1.5 hours) is a much bigger relative miss than the
same 2-minute error on a 70.3 (roughly 5-7 hours), so an absolute-minutes-
only table would make the model look uniformly worse at short distances
than it really is, and a percent-only table would hide that a "small
percentage" on a long race can still be tens of minutes.

WHY rows with `predicted is None` are dropped from the computation rather
than counted as some sentinel error: a missing prediction (no reference
performance for Riegel, `strava_estimate`'s permanent unavailability, per
DESIGN.md) is not a wrong prediction — it's the absence of a data point.
Counting it toward MAE would require either fabricating a penalty value or
treating the error as 0, both of which corrupt the average with numbers
that were never actually predicted. Excluding it and reporting a smaller
`n_races` is exactly what `eval_metrics.n_races`'s "required for inline
small-N flagging" role (DESIGN.md) is for — the caveat lives in the sample
size, not a distorted mean.

WHY `n_races == 0` returns all-null metrics rather than raising or
returning 0.0: a method with zero usable predictions in this test set
(most visibly `strava_estimate`, always) still needs a row in the report —
DESIGN.md's explicit "null if n_races = 0" contract is what renders that as
a legible "unavailable," not a crash or a fabricated perfect score.
"""

import math


def compute_metrics(pairs: list[tuple[float, float | None]]) -> dict:
    usable = [(actual, predicted) for actual, predicted in pairs if predicted is not None]
    n_races = len(usable)

    if n_races == 0:
        return {
            "n_races": 0,
            "mae_minutes": None,
            "rmse_minutes": None,
            "mae_pct": None,
            "rmse_pct": None,
        }

    abs_errors_s = [abs(actual - predicted) for actual, predicted in usable]
    sq_errors_s = [(actual - predicted) ** 2 for actual, predicted in usable]
    pct_errors = [abs(actual - predicted) / actual * 100 for actual, predicted in usable]
    sq_pct_errors = [error**2 for error in pct_errors]

    return {
        "n_races": n_races,
        "mae_minutes": (sum(abs_errors_s) / n_races) / 60,
        "rmse_minutes": math.sqrt(sum(sq_errors_s) / n_races) / 60,
        "mae_pct": sum(pct_errors) / n_races,
        "rmse_pct": math.sqrt(sum(sq_pct_errors) / n_races),
    }
