"""Race-classification heuristic — pure, deterministic, no I/O.

WHAT: `classify(name, sport_type, distance_m)` decides whether an activity
is a race and, if so, which distance category it is, using only fields
Strava's activity list endpoint already returns. `is_hard_effort` is a
second, narrower heuristic reused by feature engineering
(ingestion/feature_engineering.py) to approximate "a prior high-intensity
training day."

WHY pattern-matching on the activity title is the primary signal (per spec,
and DESIGN.md's `race_classifications` schema): Strava's API does not
expose a labelled "type of effort" beyond `sport_type` (run/ride/swim/etc)
and a sparsely-populated, inconsistent `workout_type`. How athletes actually
name a race when they log or import it ("IRONMAN 70.3 Austin", "Boston
Marathon", "Club Sprint Tri") is the most reliable signal Strava's API
surfaces — this is deliberately a heuristic with a known false-negative/
false-positive risk (an athlete who names a race "Saturday run" won't
match), which is exactly why `manual_override` exists as a first-class
schema column, not an afterthought (app/models/race.py).

WHY distance is a *fallback* signal, not the primary one, for
`distance_category`: DESIGN.md's schema note says this column is "derived
from distance_m," but title patterns like "70.3" or "Olympic" name the
category more precisely than a distance bucket can (real GPS/course
distances vary several percent race to race). So: if the matched title
pattern itself implies a category, use it; only when the match is generic
("Race", "Triathlon", a marathon-family term that Phase 1's schema doesn't
distinguish further) does `_distance_category_from_distance` bucket the
combined multisport distance against the four canonical triathlon distances.
Non-multisport activities (a plain Run/Ride) always fall back to "other" —
this project's distance-category enum only distinguishes triathlon
distances, not marathon/10k/5k.

HOW `is_hard_effort` is used: DESIGN.md flags in this module (not
feature_engineering.py) because it is a *classification* judgment, not a
window/rolling-average computation. It treats a prior confirmed race as
definitionally hard, and otherwise falls back to a small set of intensity
keywords in the title. This is a named, narrow proxy for "training stress"
— Strava's API exposes no such field — flagged here the same way DESIGN.md
flags other places where the real API diverges from an idealized spec.
"""

import re
from dataclasses import dataclass

# Order matters: more specific patterns are checked first so, e.g., "IRONMAN
# 70.3" resolves to "70.3" rather than the generic full-distance "ironman"
# pattern below it.
_RACE_NAME_PATTERNS: list[tuple[re.Pattern[str], str | None]] = [
    (re.compile(r"70\.3", re.IGNORECASE), "70.3"),
    (re.compile(r"half[\s-]*iron\s*man", re.IGNORECASE), "70.3"),
    (re.compile(r"iron\s*man", re.IGNORECASE), "full"),
    (re.compile(r"\bfull[\s-]distance\b", re.IGNORECASE), "full"),
    (re.compile(r"\bolympic\b", re.IGNORECASE), "olympic"),
    (re.compile(r"\bsprint\s+tri", re.IGNORECASE), "sprint"),
    (re.compile(r"\bmarathon\b", re.IGNORECASE), None),
    (re.compile(r"\b(5k|10k)\b", re.IGNORECASE), None),
    (re.compile(r"\btriathlon\b", re.IGNORECASE), None),
    (re.compile(r"\brace\b", re.IGNORECASE), None),
]

_HARD_EFFORT_KEYWORDS = re.compile(
    r"\b(interval|tempo|time\s*trial|tt|threshold)\b", re.IGNORECASE
)

# Combined swim+bike+run distance (meters) for each canonical triathlon
# distance. Used only as a fallback when the title doesn't already name the
# category (see module docstring).
_TRIATHLON_DISTANCE_BUCKETS_M: list[tuple[float, str]] = [
    (750 + 20_000 + 5_000, "sprint"),
    (1_500 + 40_000 + 10_000, "olympic"),
    (1_900 + 90_000 + 21_097, "70.3"),
    (3_800 + 180_000 + 42_195, "full"),
]
_DISTANCE_TOLERANCE = 0.10  # +/-10% — real courses rarely match nominal distance exactly
_MULTISPORT_TYPES = {"Triathlon", "MultisportActivity"}


@dataclass(frozen=True)
class ClassificationResult:
    is_race: bool
    matched_pattern: str | None
    distance_category: str | None


def _distance_category_from_distance(sport_type: str, distance_m: float) -> str:
    if sport_type not in _MULTISPORT_TYPES or distance_m <= 0:
        return "other"
    for target_m, category in _TRIATHLON_DISTANCE_BUCKETS_M:
        if abs(distance_m - target_m) / target_m <= _DISTANCE_TOLERANCE:
            return category
    return "other"


def classify(name: str, sport_type: str, distance_m: float) -> ClassificationResult:
    for pattern, category in _RACE_NAME_PATTERNS:
        match = pattern.search(name)
        if match:
            resolved_category = category or _distance_category_from_distance(sport_type, distance_m)
            return ClassificationResult(
                is_race=True, matched_pattern=match.group(0), distance_category=resolved_category
            )
    return ClassificationResult(is_race=False, matched_pattern=None, distance_category=None)


def is_hard_effort(name: str, *, is_race_effective: bool) -> bool:
    if is_race_effective:
        return True
    return bool(_HARD_EFFORT_KEYWORDS.search(name))
