"""Deterministic athlete train/test split — DESIGN.md's core auditability
requirement for Phase 5, built and unit-tested first given its risk profile.

WHAT: `assign_splits(user_ids, seed)` returns `{user_id: "train" | "test"}`
— a pure function with no I/O, so its correctness is checkable in isolation
from the DB, training, or prediction code that depends on it.

WHY the split is by *athlete*, not by race: a model that saw one of an
athlete's races during training would leak that athlete's specific
fitness/pacing/training-load signal into a "held-out" prediction for their
*other* race — the whole point of a held-out test set is measuring
generalization to athletes the model has never seen, not just races it
hasn't seen. Splitting any other way would overstate accuracy.

WHY the split is deterministic given `(user_ids, seed)`, not a fresh random
shuffle each call: `athlete_splits` persists this seed per `eval_run`
specifically so a reported result is reproducible and auditable — "run it
again with the same seed and same population, get the same split," which is
what makes an accuracy claim falsifiable rather than a one-off shuffle
nobody can verify.

WHY `user_ids` is sorted before seeding the shuffle: `random.Random(seed).shuffle`
is deterministic *given a starting order*, but the order rows come back from
a DB query is not itself guaranteed stable across calls/versions. Sorting
first means the same `(user_ids, seed)` pair always produces the same split
regardless of what order the caller happened to collect the ids in.

WHY at least one athlete lands in each of train/test whenever there are >=2
athletes total (test_fraction is a target, not a hard rule at this scale):
DESIGN.md's Explicit Flags already acknowledge this is a 5-10 user project
— a naive `round()` at, say, `test_fraction=0.3` and `n=3` could put zero
athletes in test, silently making the whole evaluation vacuous. With fewer
than 2 athletes, no split is possible at all; everyone goes to `"train"`
and the caller (`evaluation/report.py`) is expected to surface that
plainly rather than fabricate a test set.
"""

import random
import uuid

DEFAULT_TEST_FRACTION = 0.3


def assign_splits(
    user_ids: list[uuid.UUID], seed: int, test_fraction: float = DEFAULT_TEST_FRACTION
) -> dict[uuid.UUID, str]:
    ordered = sorted(user_ids)
    if len(ordered) < 2:
        return dict.fromkeys(ordered, "train")

    shuffled = ordered.copy()
    random.Random(seed).shuffle(shuffled)

    n_test = min(max(1, round(len(shuffled) * test_fraction)), len(shuffled) - 1)
    test_ids = set(shuffled[:n_test])

    return {user_id: ("test" if user_id in test_ids else "train") for user_id in ordered}
