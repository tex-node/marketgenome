from itertools import pairwise

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from market_genome_normalization.resampling import resample_channel, resample_channels


def test_linear_resampling_preserves_endpoints_and_length() -> None:
    result = resample_channel([0.0, 1.0], 5)
    assert result == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert result[0] == 0
    assert result[-1] == 1


def test_resampling_monotonic_constant_and_multichannel() -> None:
    monotonic = resample_channel([0, 1, 2, 3], 10)
    assert all(a <= b for a, b in pairwise(monotonic))
    assert resample_channel([2, 2, 2], 7) == [2.0] * 7
    multi = resample_channels({"open": [0, 1], "close": [1, 2]}, 3)
    assert multi == {"open": [0.0, 0.5, 1.0], "close": [1.0, 1.5, 2.0]}


def test_previous_resampling_and_errors() -> None:
    assert resample_channel([0, 1, 2], 5, method="previous")[-1] == 2
    with pytest.raises(ValueError):
        resample_channel([1], 5)
    with pytest.raises(ValueError):
        resample_channel([1, float("nan")], 5)
    with pytest.raises(ValueError):
        resample_channel([1, 2], 1)


@given(st.lists(st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False), min_size=2, max_size=30))
def test_endpoint_preservation_property(values: list[float]) -> None:
    result = resample_channel(values, 17)
    assert result[0] == pytest.approx(values[0])
    assert result[-1] == pytest.approx(values[-1])


def test_time_stretch_linear_preparation() -> None:
    base = resample_channel(list(np.linspace(0, 1, 16)), 64)
    stretched = resample_channel(list(np.linspace(0, 1, 128)), 64)
    assert np.allclose(base, stretched)
