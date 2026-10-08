from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from market_genome_diagnostics.definitions import (
    list_availability_policies,
    list_diagnostic_definitions,
    list_scaling_methods,
    list_weight_configurations,
)
from market_genome_diagnostics.service import (
    availability_aware_distance,
    distance_outcome_monotonicity,
    enforce_episode_cap,
    episode_concentration,
    feature_distribution,
    redundancy_clusters,
    scale_value,
    window_horizon_alignment,
)
from market_genome_domain.models import PatternWindow
from market_genome_features.definitions import FEATURE_DEFINITIONS, MARKET_DNA_V1_FEATURES


def _window(index: int, instrument_id: str = "inst-1") -> PatternWindow:
    start = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    return PatternWindow(
        id=f"w-{instrument_id}-{index}",
        instrument_id=instrument_id,
        timeframe_id="tf-1",
        start_timestamp=start,
        end_timestamp=start + timedelta(hours=7),
        start_bar_id=f"b-{index}",
        end_bar_id=f"b-{index + 7}",
        window_length=8,
        bar_count=8,
        source_data_hash=f"h-{instrument_id}-{index}",
        build_configuration_hash="cfg",
        is_complete=True,
        quality_flags=[],
    )


def _groups() -> dict[str, str]:
    return {feature: FEATURE_DEFINITIONS[feature].feature_group for feature in MARKET_DNA_V1_FEATURES}


def test_diagnostic_registries_expose_required_surface() -> None:
    codes = {item.code for item in list_diagnostic_definitions()}
    assert {
        "representation_quality_diagnostic_v1",
        "feature_distribution_diagnostic_v1",
        "feature_redundancy_diagnostic_v1",
        "distance_outcome_monotonicity_v1",
        "synthetic_motif_recovery_v1",
        "refined_similarity_validation_v1",
    } <= codes
    assert {"none_v1", "robust_median_mad_v1", "group_balanced_robust_v1"} <= {item.code for item in list_scaling_methods()}
    assert {"joint_available_with_coverage_penalty_v1", "group_balanced_availability_v1"} <= {item.code for item in list_availability_policies()}
    assert "shape_dna_context_balanced_v1" in {item.code for item in list_weight_configurations()}


def test_feature_distribution_and_scaling_handle_zero_mad_and_outliers() -> None:
    stats = feature_distribution([1.0, 1.0, 1.0, 100.0, None])
    assert stats["available_count"] == 4
    assert stats["unavailable_count"] == 1
    assert stats["mad"] == 0.0
    assert scale_value(1.0, stats, "robust_median_mad_v1") == pytest.approx(0.0)
    assert scale_value(100.0, stats, "winsorized_zscore_v1") is not None


def test_availability_aware_distance_policies_penalize_or_reject_low_coverage() -> None:
    q = {feature: None for feature in MARKET_DNA_V1_FEATURES}
    c = {feature: None for feature in MARKET_DNA_V1_FEATURES}
    q["normalized_endpoint_return"] = 1.0
    c["normalized_endpoint_return"] = 1.0

    penalized = availability_aware_distance(q, c, _groups(), policy="joint_available_with_coverage_penalty_v1", minimum_joint_feature_ratio=0.7)
    rejected = availability_aware_distance(q, c, _groups(), policy="minimum_coverage_reject_v1", minimum_joint_feature_ratio=0.7)

    assert penalized.rejected is False
    assert penalized.distance > 0.0
    assert "COVERAGE_PENALTY_APPLIED" in penalized.quality_flags
    assert rejected.rejected is True
    assert rejected.quality_flags == ["LOW_JOINT_FEATURE_RATIO"]


def test_redundancy_clusters_duplicate_and_negative_duplicate_features() -> None:
    rows = [
        {"a": 1.0, "b": 1.0, "c": -1.0, "d": 3.0},
        {"a": 2.0, "b": 2.0, "c": -2.0, "d": 1.0},
        {"a": 3.0, "b": 3.0, "c": -3.0, "d": 2.0},
    ]
    result = redundancy_clusters(rows, ["a", "b", "c", "d"], threshold=0.99)
    assert ["a", "b", "c"] in result["clusters"]


def test_distance_outcome_monotonicity_identifies_monotonic_flat_and_inverse_cases() -> None:
    monotonic = distance_outcome_monotonicity([{"distance": float(i), "outcome_discrepancy": float(i)} for i in range(1, 21)])
    flat = distance_outcome_monotonicity([{"distance": float(i), "outcome_discrepancy": 1.0} for i in range(1, 21)])
    inverse = distance_outcome_monotonicity([{"distance": float(i), "outcome_discrepancy": float(21 - i)} for i in range(1, 21)])
    assert monotonic["spearman"] > 0.9
    assert flat["decision"] == "FLAT_OR_INVERSE"
    assert inverse["spearman"] < -0.9


def test_episode_grouping_and_cap_are_deterministic() -> None:
    windows = [_window(0), _window(1), _window(40), _window(41), _window(0, "inst-2")]
    result = episode_concentration(windows, grouping_distance_bars=32)
    capped = enforce_episode_cap([(window, 1.0) for window in windows], maximum_per_episode=1, grouping_distance_bars=32)

    assert result["unique_episode_count"] >= 3
    assert len(capped) <= result["unique_episode_count"]
    assert episode_concentration([window for window, _ in capped], grouping_distance_bars=32)["largest_episode_share"] <= 1 / max(1, len(capped))


def test_window_horizon_alignment_matrix_is_deterministic() -> None:
    rows = window_horizon_alignment([8, 16], [1, 4, 16])
    assert rows[0] == {"window_length": 8, "horizon_bars": 1, "horizon_window_ratio": 0.125, "ratio_bucket": 0.125}
    assert len(rows) == 6
