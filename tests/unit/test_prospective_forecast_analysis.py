from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from market_genome_prospective.forecast_analysis import (
    FallbackLevelStats,
    balanced_accuracy_and_mcc,
    brier_evaluation,
    classify_prospective_decision,
    classify_sample_sufficiency,
    detect_data_revision,
    laplace_smoothed_probability,
    paired_brier_skill_bootstrap,
    per_horizon_evaluation,
    select_fallback_level,
    verify_historical_as_of,
    wilson_confidence_interval,
)


def test_wilson_confidence_interval_brackets_point_estimate() -> None:
    low, high = wilson_confidence_interval(61, 100)
    assert low < 0.61 < high
    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0


def test_wilson_confidence_interval_handles_zero_total() -> None:
    assert wilson_confidence_interval(0, 0) == (0.0, 1.0)


def test_wilson_confidence_interval_widens_for_smaller_samples() -> None:
    low_small, high_small = wilson_confidence_interval(6, 10)
    low_large, high_large = wilson_confidence_interval(600, 1000)
    assert (high_small - low_small) > (high_large - low_large)


def test_laplace_smoothed_probability_pulls_toward_half_for_tiny_samples() -> None:
    assert laplace_smoothed_probability(0, 0) == pytest.approx(0.5)
    assert laplace_smoothed_probability(1, 1) == pytest.approx(2 / 3)
    # With a large sample, smoothing barely moves the estimate off the raw frequency.
    smoothed = laplace_smoothed_probability(610, 1000)
    assert smoothed == pytest.approx(0.61, abs=0.002)


def test_classify_sample_sufficiency_thresholds() -> None:
    assert classify_sample_sufficiency(29, minimum=30) == "INSUFFICIENT_CONTEXT_HISTORY"
    assert classify_sample_sufficiency(30, minimum=30) == "FORECAST_AVAILABLE"


def test_select_fallback_level_uses_most_specific_when_sufficient() -> None:
    levels = [
        FallbackLevelStats("trend_volatility", 40, 80),
        FallbackLevelStats("trend_only", 200, 400),
        FallbackLevelStats("unconditional", 1000, 2000),
    ]
    selection = select_fallback_level(levels, minimum=30)
    assert selection.level_used == "trend_volatility"
    assert selection.fallback_reason is None
    assert selection.total_count == 80


def test_select_fallback_level_falls_back_when_most_specific_insufficient() -> None:
    levels = [
        FallbackLevelStats("trend_volatility", 5, 10),
        FallbackLevelStats("trend_only", 200, 400),
        FallbackLevelStats("unconditional", 1000, 2000),
    ]
    selection = select_fallback_level(levels, minimum=30)
    assert selection.level_used == "trend_only"
    assert selection.fallback_reason == "FALLBACK_FROM_TREND_VOLATILITY"


def test_select_fallback_level_reports_exhaustion_when_even_unconditional_is_insufficient() -> None:
    levels = [
        FallbackLevelStats("trend_volatility", 1, 2),
        FallbackLevelStats("unconditional", 3, 5),
    ]
    selection = select_fallback_level(levels, minimum=30)
    assert selection.level_used == "unconditional"
    assert selection.fallback_reason == "INSUFFICIENT_AT_ALL_FALLBACK_LEVELS"


def test_select_fallback_level_rejects_empty_hierarchy() -> None:
    with pytest.raises(ValueError, match="EMPTY_FALLBACK_HIERARCHY"):
        select_fallback_level([], minimum=30)


def test_verify_historical_as_of() -> None:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    assert verify_historical_as_of(created, created + timedelta(days=1)) is True
    assert verify_historical_as_of(created, created) is False
    assert verify_historical_as_of(created, created - timedelta(days=1)) is False


def test_detect_data_revision() -> None:
    assert detect_data_revision("abc", "abc") is False
    assert detect_data_revision("abc", "def") is True


def test_brier_evaluation_empty() -> None:
    assert brier_evaluation([]) == {"sample_count": 0}


def test_brier_evaluation_computes_skill_vs_unconditional() -> None:
    rows = [
        {"probability_positive": 0.7, "actual_positive": True},
        {"probability_positive": 0.7, "actual_positive": True},
        {"probability_positive": 0.3, "actual_positive": False},
        {"probability_positive": 0.3, "actual_positive": False},
    ]
    result = brier_evaluation(rows, unconditional_probability=0.5)
    assert result["sample_count"] == 4
    assert result["brier_score"] == pytest.approx(0.09)
    assert result["brier_skill_vs_unconditional"] == pytest.approx(1.0 - 0.09 / 0.25)
    assert result["direction_accuracy"] == pytest.approx(1.0)
    assert result["balanced_accuracy"] == pytest.approx(1.0)
    assert result["mcc"] == pytest.approx(1.0)


def test_balanced_accuracy_and_mcc_perfect_classifier() -> None:
    rows = [
        {"probability_positive": 0.9, "actual_positive": True},
        {"probability_positive": 0.8, "actual_positive": True},
        {"probability_positive": 0.1, "actual_positive": False},
        {"probability_positive": 0.2, "actual_positive": False},
    ]
    balanced_accuracy, mcc = balanced_accuracy_and_mcc(rows)
    assert balanced_accuracy == pytest.approx(1.0)
    assert mcc == pytest.approx(1.0)


def test_balanced_accuracy_and_mcc_worst_case_classifier() -> None:
    rows = [
        {"probability_positive": 0.9, "actual_positive": False},
        {"probability_positive": 0.8, "actual_positive": False},
        {"probability_positive": 0.1, "actual_positive": True},
        {"probability_positive": 0.2, "actual_positive": True},
    ]
    balanced_accuracy, mcc = balanced_accuracy_and_mcc(rows)
    assert balanced_accuracy == pytest.approx(0.0)
    assert mcc == pytest.approx(-1.0)


def test_balanced_accuracy_and_mcc_undefined_when_one_class_absent() -> None:
    """Both metrics require both classes to be represented; a degenerate rate
    (all-positive or all-negative predictions/actuals) must return None, not 0."""
    rows = [
        {"probability_positive": 0.9, "actual_positive": True},
        {"probability_positive": 0.8, "actual_positive": True},
    ]
    balanced_accuracy, mcc = balanced_accuracy_and_mcc(rows)
    assert balanced_accuracy is None
    assert mcc is None


@pytest.mark.parametrize(
    ("kwargs", "expected_decision"),
    [
        (
            {"matured_count": 10, "minimum_evidence": 100, "preferred_evidence": 250, "brier_skill_vs_unconditional": 0.1, "bootstrap_ci_low": 0.05},
            "PROSPECTIVE_EVIDENCE_ACCUMULATING",
        ),
        (
            {"matured_count": 300, "minimum_evidence": 100, "preferred_evidence": 250, "brier_skill_vs_unconditional": None, "bootstrap_ci_low": None},
            "PROSPECTIVE_EVIDENCE_ACCUMULATING",
        ),
        (
            {"matured_count": 300, "minimum_evidence": 100, "preferred_evidence": 250, "brier_skill_vs_unconditional": -0.05, "bootstrap_ci_low": None},
            "PROSPECTIVE_CONTEXT_SIGNAL_NOT_SUPPORTED",
        ),
        (
            {"matured_count": 300, "minimum_evidence": 100, "preferred_evidence": 250, "brier_skill_vs_unconditional": 0.08, "bootstrap_ci_low": 0.01},
            "PROSPECTIVE_CONTEXT_SIGNAL_SUPPORTED",
        ),
        (
            {"matured_count": 150, "minimum_evidence": 100, "preferred_evidence": 250, "brier_skill_vs_unconditional": 0.08, "bootstrap_ci_low": 0.01},
            "PROSPECTIVE_CONTEXT_SIGNAL_WEAK",
        ),
        (
            {"matured_count": 300, "minimum_evidence": 100, "preferred_evidence": 250, "brier_skill_vs_unconditional": 0.08, "bootstrap_ci_low": -0.01},
            "PROSPECTIVE_CONTEXT_SIGNAL_WEAK",
        ),
    ],
)
def test_classify_prospective_decision(kwargs: dict, expected_decision: str) -> None:
    result = classify_prospective_decision(**kwargs)
    assert result.decision == expected_decision
    assert result.rationale


def test_brier_evaluation_prefers_per_row_baseline_over_scalar() -> None:
    """A pooled set with one global scalar baseline misstates skill for rows whose own
    base rate differs; a per-row `unconditional_probability` must take precedence."""
    rows = [
        {"probability_positive": 1.0, "actual_positive": True, "unconditional_probability": 0.5},
        {"probability_positive": 0.0, "actual_positive": False, "unconditional_probability": 0.5},
    ]
    result = brier_evaluation(rows, unconditional_probability=0.9)
    assert result["brier_score"] == pytest.approx(0.0)
    assert result["brier_skill_vs_unconditional"] == pytest.approx(1.0)  # 1 - 0.0/0.25


def test_brier_evaluation_skill_is_none_when_any_row_baseline_is_missing() -> None:
    rows = [
        {"probability_positive": 1.0, "actual_positive": True, "unconditional_probability": 0.5},
        {"probability_positive": 0.0, "actual_positive": False},
    ]
    assert brier_evaluation(rows, unconditional_probability=None)["brier_skill_vs_unconditional"] is None


def test_paired_brier_skill_bootstrap_is_deterministic_and_brackets_point_estimate() -> None:
    rows = [
        {
            "probability_positive": 0.6 if (index % 3) != 0 else 0.4,
            "actual_positive": (index % 3) != 0,
            "unconditional_probability": 0.66,
            "horizon_bars": 20,
            "forecast_timestamp": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
        }
        for index in range(60)
    ]
    point = brier_evaluation(rows)["brier_skill_vs_unconditional"]
    first = paired_brier_skill_bootstrap(rows, seed=7, iterations=300)
    second = paired_brier_skill_bootstrap(rows, seed=7, iterations=300)
    assert first == second
    assert first["iterations"] == 300
    assert first["block_size"] >= 1
    assert first["low"] is not None and first["high"] is not None
    assert first["low"] <= point <= first["high"]


def test_paired_brier_skill_bootstrap_returns_none_interval_without_baseline_or_rows() -> None:
    assert paired_brier_skill_bootstrap([], seed=1)["low"] is None
    rows = [{"probability_positive": 0.5, "actual_positive": True, "horizon_bars": 20}]
    assert paired_brier_skill_bootstrap(rows, seed=1)["low"] is None


def test_per_horizon_evaluation_groups_horizons_independently() -> None:
    rows = [
        {"horizon_bars": 5, "probability_positive": 1.0, "actual_positive": True, "unconditional_probability": 0.5, "forecast_timestamp": datetime(2026, 1, 1, tzinfo=UTC)},
        {"horizon_bars": 5, "probability_positive": 0.0, "actual_positive": False, "unconditional_probability": 0.5, "forecast_timestamp": datetime(2026, 1, 2, tzinfo=UTC)},
        {"horizon_bars": 20, "probability_positive": 0.0, "actual_positive": True, "unconditional_probability": 0.5, "forecast_timestamp": datetime(2026, 1, 3, tzinfo=UTC)},
    ]
    result = per_horizon_evaluation(rows, seed=3, iterations=100)
    assert set(result) == {"5", "20"}
    assert result["5"]["sample_count"] == 2
    assert result["5"]["brier_skill_vs_unconditional"] == pytest.approx(1.0)
    assert result["20"]["sample_count"] == 1
    assert result["20"]["brier_skill_vs_unconditional"] == pytest.approx(1.0 - 1.0 / 0.25)
