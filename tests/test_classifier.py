"""Tests for the race-classification heuristic (ingestion/classifier.py) —
pure function, no DB/network, so this is the fast/exhaustive layer of
coverage for the classification logic itself (the router/DB-level behavior
of `is_race_effective` is covered by tests/test_races_router.py).
"""

import pytest

from ingestion.classifier import classify, is_hard_effort


@pytest.mark.parametrize(
    ("name", "sport_type", "distance_m", "expected_category"),
    [
        ("IRONMAN 70.3 Austin", "Run", 21_097.0, "70.3"),
        ("Half-Ironman training race", "Run", 21_097.0, "70.3"),
        ("IRONMAN Texas", "Run", 42_195.0, "full"),
        ("Full-distance tune-up", "Run", 5_000.0, "full"),
        ("Club Olympic Triathlon", "Triathlon", 51_500.0, "olympic"),
        ("Sprint Tri #3", "Triathlon", 25_750.0, "sprint"),
    ],
)
def test_classify_reads_the_category_directly_off_a_named_distance(
    name, sport_type, distance_m, expected_category
) -> None:
    result = classify(name, sport_type, distance_m)

    assert result.is_race is True
    assert result.distance_category == expected_category


def test_classify_falls_back_to_distance_bucket_for_a_generic_multisport_title() -> None:
    # "Triathlon" alone doesn't name a distance — the combined distance
    # (close to the canonical Olympic total) should resolve the category.
    result = classify("Saturday Triathlon", "MultisportActivity", 51_500.0)

    assert result.is_race is True
    assert result.distance_category == "olympic"


def test_classify_generic_race_on_a_non_multisport_activity_is_other() -> None:
    # A marathon's distance isn't one of the four triathlon buckets this
    # project's schema distinguishes — falls back to "other", not a guess.
    result = classify("Boston Marathon", "Run", 42_195.0)

    assert result.is_race is True
    assert result.distance_category == "other"


def test_classify_returns_false_for_ordinary_training_activity() -> None:
    result = classify("Tuesday easy run", "Run", 8_000.0)

    assert result.is_race is False
    assert result.matched_pattern is None
    assert result.distance_category is None


def test_is_hard_effort_true_for_any_prior_race() -> None:
    assert is_hard_effort("Sunday long run", is_race_effective=True) is True


def test_is_hard_effort_true_for_intensity_keyword() -> None:
    assert is_hard_effort("Tempo run", is_race_effective=False) is True


def test_is_hard_effort_false_for_ordinary_easy_activity() -> None:
    assert is_hard_effort("Easy recovery spin", is_race_effective=False) is False
