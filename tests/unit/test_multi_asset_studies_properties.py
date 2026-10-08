from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st
from market_genome_studies.service import quality_state, temporal_episode_gap


@given(
    st.integers(min_value=1, max_value=256),
    st.lists(st.integers(min_value=1, max_value=100), min_size=1, max_size=10),
    st.integers(min_value=0, max_value=256),
)
def test_episode_gap_is_at_least_window_horizon_and_minimum(window_length: int, horizons: list[int], minimum: int) -> None:
    gap = temporal_episode_gap(window_length, horizons, minimum)
    assert gap >= window_length
    assert gap >= max(horizons)
    assert gap >= minimum


@given(
    st.integers(min_value=0, max_value=200),
    st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False),
)
def test_quality_state_is_valid_enum(unique_episodes: int, largest: float, top_three: float) -> None:
    cfg = {"minimum_unique_episodes": 30, "maximum_single_episode_share": 0.10, "maximum_top_three_episode_share": 0.25}
    state = quality_state(unique_episodes, largest, max(largest, top_three), cfg)
    assert state in {"ADEQUATE", "MARGINAL", "INADEQUATE"}
