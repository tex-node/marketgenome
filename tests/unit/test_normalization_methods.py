from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from market_genome_domain.models import PriceBar
from market_genome_normalization.methods import get_method, list_methods
from market_genome_normalization.service import (
    NormalizationPolicies,
    normalization_configuration_hash,
    normalize_bars,
    representation_hash,
)


def _bars(closes: list[float], scale: float = 1.0) -> list[PriceBar]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    bars = []
    for idx, close in enumerate(closes):
        price = close * scale
        bars.append(
            PriceBar(
                id=f"bar-{idx}",
                instrument_id="instrument",
                timeframe_id="timeframe",
                source_id="source",
                timestamp=start + timedelta(hours=idx),
                open=price - 0.1 * scale,
                high=price + 0.5 * scale,
                low=price - 0.5 * scale,
                close=price,
                volume=1000 + idx,
                data_quality_flags=[],
            )
        )
    return bars


def test_method_registry_contains_required_methods() -> None:
    codes = {method.code for method in list_methods()}
    assert {
        "anchored_simple_return",
        "anchored_log_return",
        "zscore_close",
        "range_close",
        "volatility_targeted_return",
        "atr_anchored_ohlc",
        "anchored_ohlc",
    }.issubset(codes)


def test_anchored_simple_return_scaling_and_direction() -> None:
    values, _, _ = normalize_bars(_bars([10, 12, 11]), get_method("anchored_simple_return"), NormalizationPolicies())
    scaled, _, _ = normalize_bars(_bars([10, 12, 11], scale=10), get_method("anchored_simple_return"), NormalizationPolicies())
    assert values["close"][0] == 0
    assert values == scaled
    assert values["close"][1] > 0
    assert values["close"][2] > 0


def test_anchored_log_return_rejects_non_positive() -> None:
    with pytest.raises(ValueError, match="NORMALIZATION_NON_POSITIVE_PRICE"):
        normalize_bars(_bars([10, 0, 11]), get_method("anchored_log_return"), NormalizationPolicies())


def test_anchored_ohlc_preserves_order_and_scaling() -> None:
    values, _, _ = normalize_bars(_bars([10, 11, 12]), get_method("anchored_ohlc"), NormalizationPolicies())
    scaled, _, _ = normalize_bars(_bars([10, 11, 12], scale=100), get_method("anchored_ohlc"), NormalizationPolicies())
    assert list(values) == ["open", "high", "low", "close"]
    assert values == scaled
    for idx in range(3):
        assert values["low"][idx] <= values["open"][idx] <= values["high"][idx]
        assert values["low"][idx] <= values["close"][idx] <= values["high"][idx]


def test_zscore_close_and_zero_variance_policy() -> None:
    values, _, _ = normalize_bars(_bars([1, 2, 3, 4]), get_method("zscore_close"), NormalizationPolicies())
    assert np.mean(values["close"]) == pytest.approx(0)
    assert np.std(values["close"]) == pytest.approx(1)
    with pytest.raises(ValueError, match="NORMALIZATION_ZERO_VARIANCE"):
        normalize_bars(_bars([2, 2, 2]), get_method("zscore_close"), NormalizationPolicies())
    zeroed, flags, _ = normalize_bars(
        _bars([2, 2, 2]),
        get_method("zscore_close"),
        NormalizationPolicies(zero_variance="all_zero_with_flag"),
    )
    assert zeroed["close"] == [0.0, 0.0, 0.0]
    assert "ZERO_VARIANCE" in flags


def test_range_close_and_centering() -> None:
    values, _, _ = normalize_bars(_bars([10, 15, 20]), get_method("range_close"), NormalizationPolicies())
    centered, _, _ = normalize_bars(
        _bars([10, 15, 20]),
        get_method("range_close"),
        NormalizationPolicies(range_centered=True),
    )
    assert min(values["close"]) == 0
    assert max(values["close"]) == 1
    assert centered["close"] == [-1.0, 0.0, 1.0]


def test_volatility_targeted_and_atr_methods() -> None:
    vol, _, diagnostics = normalize_bars(
        _bars([10, 11, 10.5, 12]),
        get_method("volatility_targeted_return"),
        NormalizationPolicies(),
    )
    assert vol["close"][0] == 0
    assert diagnostics["source_realized_volatility"] > 0
    atr, _, atr_diag = normalize_bars(_bars([10, 11, 12]), get_method("atr_anchored_ohlc"), NormalizationPolicies())
    assert set(atr) == {"open", "high", "low", "close"}
    assert atr_diag["source_atr"] > 0


def test_volume_relative_mean() -> None:
    values, _, _ = normalize_bars(_bars([10, 11, 12]), get_method("volume_relative_mean"), NormalizationPolicies())
    assert np.mean(values["volume"]) == pytest.approx(1)


def test_hashes_are_canonical_and_sensitive() -> None:
    assert normalization_configuration_hash({"b": 2, "a": 1}) == normalization_configuration_hash({"a": 1, "b": 2})
    first = representation_hash({"values": {"close": [0, 1]}, "points": 2})
    second = representation_hash({"values": {"close": [0, 1]}, "points": 3})
    assert first != second


@given(
    st.lists(st.floats(min_value=1, max_value=1000, allow_nan=False, allow_infinity=False), min_size=3, max_size=20),
    st.floats(min_value=0.1, max_value=1000, allow_nan=False, allow_infinity=False),
)
def test_price_scaling_invariance_property(prices: list[float], scale: float) -> None:
    values, _, _ = normalize_bars(_bars(prices), get_method("anchored_log_return"), NormalizationPolicies())
    scaled, _, _ = normalize_bars(_bars(prices, scale=scale), get_method("anchored_log_return"), NormalizationPolicies())
    assert np.allclose(values["close"], scaled["close"])

