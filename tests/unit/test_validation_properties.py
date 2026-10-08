from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st
from market_genome_validation.service import (
    benjamini_hochberg,
    brier_score,
    calibration_metrics,
    configuration_hash,
    effective_sample_size,
    holm,
    weights_for,
)


@given(st.lists(st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False), min_size=1, max_size=25))
def test_weighting_methods_are_probability_distributions(distances: list[float]) -> None:
    for method in ("uniform_v1", "inverse_distance_v1", "softmax_similarity_v1", "rank_decay_v1"):
        weights = weights_for(method, distances)
        assert len(weights) == len(distances)
        assert abs(sum(weights) - 1.0) < 1e-9
        assert all(0.0 <= weight <= 1.0 for weight in weights)
        assert 1.0 <= effective_sample_size(weights) <= len(weights)


@given(st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False), st.booleans())
def test_brier_score_is_clipped_to_unit_interval(probability: float, actual_positive: bool) -> None:
    assert 0.0 <= brier_score(probability, actual_positive) <= 1.0


@given(st.lists(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False), min_size=1, max_size=40))
def test_calibration_metrics_are_bounded(probabilities: list[float]) -> None:
    actual = [probability >= 0.5 for probability in probabilities]
    metrics = calibration_metrics(probabilities, actual, bins=5)
    assert 0.0 <= metrics["ece"] <= 1.0
    assert 0.0 <= metrics["mce"] <= 1.0


@given(st.lists(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False), min_size=1, max_size=20))
def test_multiple_testing_adjustments_are_bounded_and_not_smaller_than_raw(p_values: list[float]) -> None:
    for adjusted in (benjamini_hochberg(p_values), holm(p_values)):
        assert len(adjusted) == len(p_values)
        assert all(0.0 <= value <= 1.0 for value in adjusted)
        assert all(value >= raw for value, raw in zip(adjusted, p_values, strict=False))


def test_configuration_hash_is_order_independent() -> None:
    assert configuration_hash({"a": 1, "b": {"c": 2}}) == configuration_hash({"b": {"c": 2}, "a": 1})
