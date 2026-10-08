from __future__ import annotations

from copy import deepcopy

import pytest
from hypothesis import given
from hypothesis import strategies as st
from market_genome_context.definitions import TRANSPARENT_CONTEXT_V1, list_context_dimensions
from market_genome_context.service import (
    classify_market_context,
    classify_multi_resolution,
    context_configuration_hash,
)
from market_genome_domain.models import MarketDNA


def _dna(**overrides) -> MarketDNA:
    features = {
        "linear_regression_slope": 0.12,
        "linear_regression_r_squared": 0.8,
        "path_efficiency_ratio": 0.7,
        "trend_direction_consistency": 0.75,
        "normalized_endpoint_return": 0.16,
        "path_displacement": 0.16,
        "momentum_acceleration": 0.01,
        "higher_high_count": 2,
        "higher_low_count": 2,
        "lower_high_count": 0,
        "lower_low_count": 0,
        "realized_volatility": 0.02,
        "return_std": 0.02,
        "normalized_atr": 0.015,
        "upper_tail_ratio": 1.2,
        "lower_tail_ratio": 1.1,
        "volatility_expansion_ratio": 1.0,
        "range_expansion_ratio": 1.0,
        "hurst_rs_v1": 0.6,
        "ar_1_coefficient": 0.2,
        "lag_1_autocorrelation": 0.2,
        "variance_ratio_2": 1.2,
        "variance_ratio_4": 1.2,
        "relative_volume_mean": 1.0,
        "volume_coefficient_of_variation": 0.2,
        "volume_expansion_ratio": 1.0,
        "volume_trend_slope": 0.0,
        "maximum_positive_return": 0.025,
        "maximum_negative_return": -0.018,
        "path_length": 0.3,
    }
    features.update(overrides)
    return MarketDNA(
        id="dna",
        pattern_window_id="window",
        normalized_pattern_id="normalized",
        feature_set_code="market_dna_v1",
        feature_set_version="market_dna_v1",
        source_window_hash="w",
        source_representation_hash="r",
        configuration_hash="c",
        feature_vector_hash="f",
        feature_count=len(features),
        available_feature_count=len(features),
        unavailable_feature_count=0,
        feature_vector={},
        feature_values=features,
        availability={key: "AVAILABLE" for key in features},
        diagnostics={},
        quality_flags=[],
    )


def test_context_registry_defines_required_dimensions() -> None:
    dimensions = {item["code"] for item in list_context_dimensions()}

    assert dimensions == set(TRANSPARENT_CONTEXT_V1.dimensions)
    assert TRANSPARENT_CONTEXT_V1.is_supervised is False
    assert TRANSPARENT_CONTEXT_V1.uses_future_outcomes is False


def test_strong_uptrend_context_and_codes_are_deterministic() -> None:
    first = classify_market_context(_dna(), multi_resolution_links={
        "intermediate": {"trend_state": "STRONG_UPTREND"},
        "macro": {"trend_state": "WEAK_UPTREND"},
    })
    second = classify_market_context(_dna(), multi_resolution_links={
        "intermediate": {"trend_state": "STRONG_UPTREND"},
        "macro": {"trend_state": "WEAK_UPTREND"},
    })

    assert first.states["trend"] == "STRONG_UPTREND"
    assert first.states["multi_resolution"] == "ALIGNED_BULLISH"
    assert first.context_family_code == "BULL_TREND_LOW_VOL"
    assert first.context_hash == second.context_hash
    assert first.composite_context_code == second.composite_context_code


@pytest.mark.parametrize(
    ("slope", "expected"),
    [(0.06, "WEAK_UPTREND"), (0.0, "RANGE"), (-0.06, "WEAK_DOWNTREND"), (-0.14, "STRONG_DOWNTREND")],
)
def test_trend_states(slope: float, expected: str) -> None:
    result = classify_market_context(_dna(linear_regression_slope=slope, normalized_endpoint_return=slope * 2))

    assert result.states["trend"] == expected


@pytest.mark.parametrize(
    ("volatility", "expected"),
    [(0.001, "VERY_LOW"), (0.012, "LOW"), (0.025, "NORMAL"), (0.04, "HIGH"), (0.08, "EXTREME")],
)
def test_volatility_states(volatility: float, expected: str) -> None:
    result = classify_market_context(_dna(realized_volatility=volatility, return_std=volatility, normalized_atr=volatility))

    assert result.states["volatility"] == expected


def test_missing_volume_activity_is_unavailable() -> None:
    dna = _dna()
    dna.availability = deepcopy(dna.availability)
    for code in ("relative_volume_mean", "volume_coefficient_of_variation", "volume_expansion_ratio", "volume_trend_slope"):
        dna.availability[code] = "UNAVAILABLE_MISSING_CHANNEL"
        dna.feature_values[code] = None

    result = classify_market_context(dna)

    assert result.states["activity"] == "UNAVAILABLE"
    assert result.confidences["activity"] == 0.0


def test_shock_severity_and_phase() -> None:
    event_like = classify_market_context(_dna(return_std=0.01, maximum_positive_return=0.04, path_length=0.4))
    discontinuous = classify_market_context(_dna(return_std=0.01, maximum_positive_return=0.08, path_length=0.1))
    compressing = classify_market_context(_dna(volatility_expansion_ratio=0.5, range_expansion_ratio=0.6))

    assert event_like.states["shock"] in {"EVENT_LIKE", "DISCONTINUOUS"}
    assert discontinuous.states["shock"] == "DISCONTINUOUS"
    assert compressing.states["volatility_phase"] == "COMPRESSING"


def test_multi_resolution_states() -> None:
    assert classify_multi_resolution("WEAK_UPTREND", {"intermediate": {"trend_state": "RANGE"}, "macro": {"trend_state": "WEAK_DOWNTREND"}}).state == "LOCAL_BULLISH_MACRO_BEARISH"
    assert classify_multi_resolution("RANGE", {}).state == "UNAVAILABLE"


@given(st.floats(min_value=-0.2, max_value=0.2, allow_nan=False, allow_infinity=False))
def test_confidence_and_completeness_bounds(slope: float) -> None:
    result = classify_market_context(_dna(linear_regression_slope=slope, normalized_endpoint_return=slope))

    assert 0.0 <= result.composite_confidence <= 1.0
    assert 0.0 <= result.completeness_score <= 1.0
    assert all(0.0 <= value <= 1.0 for value in result.confidences.values())


def test_configuration_hash_changes_with_thresholds() -> None:
    config = deepcopy(TRANSPARENT_CONTEXT_V1.configuration_schema)
    changed = deepcopy(config)
    changed["trend"]["weak_slope_threshold"] = 0.04

    assert context_configuration_hash(config) != context_configuration_hash(changed)
