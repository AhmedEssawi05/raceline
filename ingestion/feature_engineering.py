"""Training-load feature engineering — pure functions over plain data, no
ORM/DB access, so the windowing logic is unit-testable without a database
(see tests/test_feature_engineering.py).

WHAT: `compute_training_load_features` takes one race's own fields plus its
athlete's full prior-activity history (already loaded and sorted by the
caller, worker/jobs/compute_features.py) and returns the exact field dict
`training_load_features` needs, with explicit null handling wherever a
window has insufficient history — per DESIGN.md's "null if insufficient
trailing history" contract.

WHY the caller passes `PriorActivitySample` (a small plain dataclass), not
ORM `Activity` rows: keeping this module free of SQLAlchemy means every
window/threshold rule below can be unit tested with hand-built lists, no
test database required, which matters given DESIGN.md calls this module's
null-handling correctness out explicitly.

WHY these specific windows/thresholds (all named constants below, not
buried in the function body): they are informal training-load heuristics,
not derived from data — flagged here the same way DESIGN.md flags other
places this project makes an explicit, documented assumption rather than a
data-backed claim:
  - `DEFAULT_WINDOW_DAYS = 28` (4 weeks): a standard "recent training load"
    lookback in endurance coaching — long enough to average out single bad/
    good weeks, short enough to reflect current fitness rather than a whole
    training cycle.
  - `_TAPER_RECENT_DAYS = 7`: tapering is conventionally described in
    single final weeks before a race.
  - `_TAPER_THRESHOLD_RATIO = 0.5`: the final week's volume falling below
    half of the preceding 3-week average is a common informal definition of
    "this looks like a taper" — a judgment call, not a calibrated cutoff.
  - Hard-effort lookback is intentionally *not* capped to `window_days`:
    "days since last hard effort" can legitimately be larger than the
    rolling-load window (e.g. an athlete coming back from a long easy
    block), so it searches the athlete's full supplied history instead of
    truncating it to the same window as the mileage features.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

DEFAULT_WINDOW_DAYS = 28
_TAPER_RECENT_DAYS = 7
_TAPER_THRESHOLD_RATIO = 0.5
_RUN_SPORT_TYPES = {"Run", "TrailRun", "VirtualRun"}


@dataclass(frozen=True)
class PriorActivitySample:
    start_date: datetime
    distance_m: float
    moving_time_s: int
    sport_type: str
    is_hard_effort: bool


def _weekly_average(total: float, window_days: int) -> float:
    return total / (window_days / 7)


def compute_training_load_features(
    *,
    race_start_date: datetime,
    race_avg_heart_rate: float | None,
    race_avg_power_w: float | None,
    prior_activities: list[PriorActivitySample],
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict:
    window_start = race_start_date - timedelta(days=window_days)
    in_window = [a for a in prior_activities if window_start <= a.start_date < race_start_date]

    if not in_window:
        rolling_weekly_mileage_m = None
        rolling_weekly_duration_s = None
        long_run_distance_4wk_m = None
        taper_indicator = None
    else:
        rolling_weekly_mileage_m = _weekly_average(
            sum(a.distance_m for a in in_window), window_days
        )
        rolling_weekly_duration_s = _weekly_average(
            sum(a.moving_time_s for a in in_window), window_days
        )
        run_distances = [a.distance_m for a in in_window if a.sport_type in _RUN_SPORT_TYPES]
        long_run_distance_4wk_m = max(run_distances) if run_distances else None
        taper_indicator = _compute_taper_indicator(race_start_date, in_window)

    days_since_last_hard_effort = _compute_days_since_last_hard_effort(
        race_start_date, prior_activities
    )

    return {
        "rolling_weekly_mileage_m": rolling_weekly_mileage_m,
        "rolling_weekly_duration_s": rolling_weekly_duration_s,
        "long_run_distance_4wk_m": long_run_distance_4wk_m,
        "days_since_last_hard_effort": days_since_last_hard_effort,
        "taper_indicator": taper_indicator,
        "avg_hr_available": race_avg_heart_rate is not None,
        "avg_power_available": race_avg_power_w is not None,
        "feature_window_days": window_days,
        "extra_features": None,
    }


def _compute_taper_indicator(
    race_start_date: datetime, in_window: list[PriorActivitySample]
) -> bool | None:
    recent_cutoff = race_start_date - timedelta(days=_TAPER_RECENT_DAYS)
    recent = [a for a in in_window if a.start_date >= recent_cutoff]
    baseline = [a for a in in_window if a.start_date < recent_cutoff]
    if not baseline:
        return None  # nothing to compare the recent week against

    baseline_days = (recent_cutoff - min(a.start_date for a in baseline)).days or 1
    baseline_weekly_avg = _weekly_average(sum(a.distance_m for a in baseline), baseline_days)
    if baseline_weekly_avg <= 0:
        return None

    recent_distance = sum(a.distance_m for a in recent)
    return recent_distance < _TAPER_THRESHOLD_RATIO * baseline_weekly_avg


def _compute_days_since_last_hard_effort(
    race_start_date: datetime, prior_activities: list[PriorActivitySample]
) -> int | None:
    hard_efforts = [a.start_date for a in prior_activities if a.is_hard_effort]
    if not hard_efforts:
        return None
    return (race_start_date - max(hard_efforts)).days
