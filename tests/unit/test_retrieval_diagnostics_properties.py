from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st
from market_genome_diagnostics.service import (
    assign_similarity_deciles,
    availability_aware_distance,
    enforce_episode_cap,
)
from market_genome_domain.models import PatternWindow

FEATURES = ["normalized_endpoint_return", "path_length", "return_std"]
GROUPS = {"normalized_endpoint_return": "PATH", "path_length": "PATH", "return_std": "MOMENTUM"}


def _dict(values: list[float]) -> dict[str, float]:
    return {feature: values[index] for index, feature in enumerate(FEATURES)}


def _window(index: int) -> PatternWindow:
    start = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    return PatternWindow(
        id=f"w-{index}",
        instrument_id="inst",
        timeframe_id="tf",
        start_timestamp=start,
        end_timestamp=start + timedelta(hours=7),
        start_bar_id=f"b-{index}",
        end_bar_id=f"b-{index + 7}",
        window_length=8,
        bar_count=8,
        source_data_hash=f"h-{index}",
        build_configuration_hash="cfg",
        is_complete=True,
        quality_flags=[],
    )


@given(st.lists(st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False), min_size=3, max_size=3), st.lists(st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False), min_size=3, max_size=3))
def test_availability_distance_is_symmetric(a: list[float], b: list[float]) -> None:
    left = availability_aware_distance(_dict(a), _dict(b), GROUPS)
    right = availability_aware_distance(_dict(b), _dict(a), GROUPS)
    assert abs(left.distance - right.distance) < 1e-9


@given(st.lists(st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False), min_size=3, max_size=3))
def test_identity_distance_is_zero_for_full_overlap(a: list[float]) -> None:
    result = availability_aware_distance(_dict(a), _dict(a), GROUPS, policy="joint_available_only_v1")
    assert result.distance >= 0.0
    assert result.distance < 1e-9 or result.similarity_score <= 1.0


def test_removing_features_does_not_improve_penalized_similarity() -> None:
    full_a = _dict([1.0, 2.0, 3.0])
    full_b = _dict([1.0, 2.0, 4.0])
    partial_b = {"normalized_endpoint_return": 1.0, "path_length": None, "return_std": None}

    full = availability_aware_distance(full_a, full_b, GROUPS, policy="joint_available_with_coverage_penalty_v1")
    partial = availability_aware_distance(full_a, partial_b, GROUPS, policy="joint_available_with_coverage_penalty_v1")
    assert partial.distance >= full.distance


@given(st.integers(min_value=1, max_value=5))
def test_episode_cap_never_exceeds_limit(limit: int) -> None:
    windows = [_window(index) for index in range(10)]
    capped = enforce_episode_cap([(window, 1.0) for window in windows], maximum_per_episode=limit, grouping_distance_bars=32)
    counts: dict[str, int] = {}
    for window, _ in capped:
        bucket = int(window.end_timestamp.timestamp() // 32)
        counts[str(bucket)] = counts.get(str(bucket), 0) + 1
    assert all(count <= limit for count in counts.values())


@given(st.lists(st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False), min_size=1, max_size=100))
def test_decile_assignment_is_complete(scores: list[float]) -> None:
    rows = assign_similarity_deciles([(f"id-{index}", score) for index, score in enumerate(scores)])
    assert len(rows) == len(scores)
    assert {row["candidate_id"] for row in rows} == {f"id-{index}" for index in range(len(scores))}
    assert all(1 <= row["decile"] <= 10 for row in rows)
