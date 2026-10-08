from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from market_genome_domain.models import OutcomeObservation, PatternWindow
from market_genome_validation.definitions import (
    list_baseline_methods,
    list_experiment_definitions,
    list_metric_definitions,
    list_validation_methods,
    list_weighting_methods,
)
from market_genome_validation.service import (
    aggregate_outcomes,
    benjamini_hochberg,
    bootstrap_ci,
    brier_score,
    calibration_metrics,
    check_candidate_eligibility,
    classification_metrics,
    deterministic_seed,
    effective_sample_size,
    experiment_decision,
    generate_folds,
    holm,
    log_loss,
    pinball_loss,
    weights_for,
)


def _window(index: int, *, instrument_id: str = "inst-1", length: int = 4) -> PatternWindow:
    start = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    return PatternWindow(
        id=f"window-{index}-{instrument_id}",
        instrument_id=instrument_id,
        timeframe_id="tf-1",
        start_timestamp=start,
        end_timestamp=start + timedelta(hours=length - 1),
        start_bar_id=f"bar-{index}",
        end_bar_id=f"bar-{index + length - 1}",
        window_length=length,
        bar_count=length,
        source_data_hash=f"hash-{index}-{instrument_id}",
        build_configuration_hash="cfg",
        is_complete=True,
        quality_flags=[],
    )


def _outcome(index: int, value: float, *, complete: bool = True) -> OutcomeObservation:
    now = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    return OutcomeObservation(
        id=f"outcome-{index}",
        pattern_window_id=f"window-{index}",
        instrument_id="inst-1",
        timeframe_id="tf-1",
        window_length=4,
        window_start_timestamp=now,
        window_end_timestamp=now + timedelta(hours=3),
        outcome_set_code="forward_outcomes_v1",
        outcome_set_version="outcome_v1",
        horizon_bars=1,
        available_future_bars=1,
        is_complete=complete,
        anchor_timestamp=now + timedelta(hours=3),
        anchor_price=100.0,
        first_future_timestamp=now + timedelta(hours=4),
        last_future_timestamp=now + timedelta(hours=4),
        future_simple_return=value,
        future_log_return=value,
        maximum_favourable_excursion=max(value, 0.0),
        maximum_adverse_excursion=min(value, 0.0),
        future_realized_volatility=0.0,
        direction_class="UP" if value > 0 else "DOWN" if value < 0 else "FLAT",
        continuation_reversal_class="CONTINUATION" if value > 0 else "REVERSAL",
        first_barrier_hit="NONE",
        gain_before_drawdown="NONE",
        drawdown_before_gain="NONE",
        source_window_hash="window-hash",
        future_bar_hash="future-hash",
        configuration_hash="cfg",
        outcome_hash=f"hash-{index}",
        scalar_values={"future_simple_return": value},
        forward_path={"values": [0.0, value]},
        barrier_results={},
        diagnostics={},
        quality_flags=[],
    )


def test_validation_registries_include_required_phase_1_surface() -> None:
    experiment_codes = {item.code for item in list_experiment_definitions()}
    baseline_codes = {item.code for item in list_baseline_methods()}
    metric_codes = {item.code for item in list_metric_definitions()}
    validation_codes = {item.code for item in list_validation_methods()}
    weighting_codes = {item.code for item in list_weighting_methods()}

    assert {
        "walk_forward_analogue_validation_v1",
        "purged_cv_analogue_validation_v1",
        "baseline_comparison_v1",
        "calibration_analysis_v1",
    } <= experiment_codes
    assert {
        "random_history_v1",
        "same_instrument_random_v1",
        "same_context_random_v1",
        "raw_shape_euclidean_v1",
        "unconditional_outcome_v1",
        "naive_continuation_v1",
        "recent_mean_return_v1",
    } <= baseline_codes
    assert {"expanding_walk_forward_v1", "rolling_walk_forward_v1", "purged_kfold_v1", "anchored_holdout_v1"} <= validation_codes
    assert {"brier_score", "log_loss", "direction_accuracy", "expected_calibration_error"} <= metric_codes
    assert {"uniform_v1", "inverse_distance_v1", "softmax_similarity_v1", "rank_decay_v1"} <= weighting_codes


def test_candidate_eligibility_rejects_future_self_overlap_and_embargo() -> None:
    query = _window(10)
    historical = _window(0)
    contemporary = _window(10)
    future = _window(11)
    overlapping = _window(8)
    near = _window(6)

    assert check_candidate_eligibility(query, historical, 1).eligible
    assert check_candidate_eligibility(query, contemporary, 1).reason == "SAME_QUERY"
    assert check_candidate_eligibility(query, future, 1).reason == "FUTURE_OR_CONTEMPORARY"
    assert check_candidate_eligibility(query, overlapping, 1).reason == "SOURCE_OVERLAP"
    assert check_candidate_eligibility(query, near, 1, embargo_bars=5).reason == "EMBARGO_OR_TEMPORAL_DISTANCE"
    assert check_candidate_eligibility(query, _window(0, instrument_id="inst-2"), 1, allow_cross_asset=False).reason == "CROSS_ASSET_EXCLUDED"
    assert check_candidate_eligibility(query, historical, 1, allow_same_instrument=False).reason == "SAME_INSTRUMENT_EXCLUDED"


def test_fold_generation_is_deterministic_and_rejects_insufficient_history() -> None:
    windows = [_window(index) for index in range(16)]
    first = generate_folds(windows, "expanding_walk_forward_v1", {"minimum_index_windows": 5, "test_window_count": 2, "fold_count": 2})
    second = generate_folds(list(reversed(windows)), "expanding_walk_forward_v1", {"minimum_index_windows": 5, "test_window_count": 2, "fold_count": 2})

    assert [fold.fold_hash for fold in first] == [fold.fold_hash for fold in second]
    assert first[0].index_end < first[0].test_start
    assert generate_folds(windows, "rolling_walk_forward_v1", {"minimum_index_windows": 5, "rolling_index_window_count": 3})[0].configuration["rolling_index_window_count"] == 3
    assert generate_folds(windows, "anchored_holdout_v1", {"minimum_index_windows": 5})[0].index_start == windows[0].end_timestamp
    with pytest.raises(ValueError, match="EXPERIMENT_NO_ELIGIBLE_QUERIES"):
        generate_folds(windows[:3], "expanding_walk_forward_v1", {"minimum_index_windows": 5})


def test_weights_aggregation_metrics_and_decision_helpers_are_bounded() -> None:
    distances = [0.1, 0.3, 0.8]
    for method in ("uniform_v1", "inverse_distance_v1", "softmax_similarity_v1", "rank_decay_v1"):
        weights = weights_for(method, distances, similarities=[0.9, 0.5, 0.1])
        assert sum(weights) == pytest.approx(1.0)
        assert 1.0 <= effective_sample_size(weights) <= len(weights)

    aggregate = aggregate_outcomes([_outcome(1, 0.02), _outcome(2, -0.01), _outcome(3, 0.0, complete=False)], [0.7, 0.3, 0.0])
    assert aggregate["complete_outcome_count"] == 2
    assert aggregate["positive_frequency"] == pytest.approx(0.7)
    assert aggregate["negative_frequency"] == pytest.approx(0.3)
    assert brier_score(0.7, True) == pytest.approx(0.09)
    assert 0.0 < log_loss(0.7, True) < 1.0
    assert pinball_loss(1.0, 0.0, 0.9) == pytest.approx(0.9)
    assert classification_metrics([True, False, True], [True, False, False])["accuracy"] == pytest.approx(2 / 3)

    calibration = calibration_metrics([0.1, 0.9], [False, True], bins=2)
    assert 0.0 <= calibration["ece"] <= 1.0
    assert bootstrap_ci([1.0, 2.0, 3.0], seed=deterministic_seed("x"))["standard_error"] is not None
    assert all(0.0 <= p <= 1.0 for p in benjamini_hochberg([0.01, 0.2, 0.5]))
    assert all(0.0 <= p <= 1.0 for p in holm([0.01, 0.2, 0.5]))
    assert experiment_decision({"brier_skill_score": 0.1, "direction_accuracy": 0.6, "skill_ci_low": -0.1}, 20) == "PROMISING"
