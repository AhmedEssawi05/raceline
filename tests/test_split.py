"""Tests for evaluation/split.py — the heaviest-coverage, highest-risk test
file in Phase 5, per DESIGN.md's own stated priority: an incorrect split
would silently invalidate every accuracy number the evaluation report
produces.
"""

import uuid

from evaluation.split import assign_splits

USER_IDS = [uuid.uuid4() for _ in range(10)]


def test_same_seed_and_population_always_produces_the_same_split() -> None:
    first = assign_splits(USER_IDS, seed=7)
    second = assign_splits(list(reversed(USER_IDS)), seed=7)  # different input order

    assert first == second


def test_different_seeds_can_produce_different_splits() -> None:
    first = assign_splits(USER_IDS, seed=1)
    second = assign_splits(USER_IDS, seed=2)

    assert first != second


def test_every_user_is_assigned_exactly_once() -> None:
    split = assign_splits(USER_IDS, seed=7)

    assert set(split) == set(USER_IDS)
    assert set(split.values()) <= {"train", "test"}


def test_both_train_and_test_are_nonempty_with_enough_athletes() -> None:
    split = assign_splits(USER_IDS, seed=7)

    assert "train" in split.values()
    assert "test" in split.values()


def test_single_athlete_goes_to_train_with_no_test_set() -> None:
    lone_user = uuid.uuid4()

    split = assign_splits([lone_user], seed=7)

    assert split == {lone_user: "train"}


def test_empty_population_returns_empty_split() -> None:
    assert assign_splits([], seed=7) == {}


def test_two_athletes_always_split_one_and_one() -> None:
    pair = USER_IDS[:2]

    split = assign_splits(pair, seed=7)

    assert sorted(split.values()) == ["test", "train"]


def test_test_fraction_is_approximately_respected_at_larger_n() -> None:
    many_users = [uuid.uuid4() for _ in range(20)]

    split = assign_splits(many_users, seed=7, test_fraction=0.3)

    n_test = sum(1 for assignment in split.values() if assignment == "test")
    assert n_test == 6  # round(20 * 0.3)
