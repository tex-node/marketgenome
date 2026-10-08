from __future__ import annotations

import numpy as np
import pytest
from market_genome_features.definitions import (
    MARKET_DNA_V1,
    MARKET_DNA_V1_FEATURES,
    list_feature_definitions,
)
from market_genome_features.service import (
    AVAILABLE,
    FeatureContext,
    compute_market_dna,
    feature_vector_hash,
)


def _context(scale: float = 1.0, volume: np.ndarray | None = None) -> FeatureContext:
    base = np.linspace(100.0, 118.0, 64) + np.sin(np.linspace(0, 10, 64)) * 2.0
    close = base * scale
    open_ = (base - 0.25) * scale
    high = (base + 1.0) * scale
    low = (base - 1.0) * scale
    normalized = np.log(close / close[0])
    return FeatureContext(
        normalized_close=normalized,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume if volume is not None else np.linspace(1000.0, 1600.0, 64),
    )


def test_market_dna_v1_registry_is_ordered_and_complete() -> None:
    definitions = list_feature_definitions()

    assert [item.code for item in definitions] == MARKET_DNA_V1_FEATURES
    assert len(definitions) == len(MARKET_DNA_V1.ordered_feature_codes)
    assert len({item.code for item in definitions}) == len(definitions)


def test_compute_market_dna_returns_explicit_status_for_every_feature() -> None:
    result = compute_market_dna(_context(), MARKET_DNA_V1)

    assert set(result.feature_values) == set(MARKET_DNA_V1_FEATURES)
    assert set(result.availability) == set(MARKET_DNA_V1_FEATURES)
    assert result.diagnostics["feature_count"] == len(MARKET_DNA_V1_FEATURES)
    assert result.diagnostics["available_feature_count"] > 60
    assert result.feature_values["path_efficiency_ratio"] <= 1.0
    assert 0.0 <= result.feature_values["endpoint_position_in_range"] <= 1.0
    assert 0.0 <= result.feature_values["permutation_entropy"] <= 1.0


def test_feature_computation_is_deterministic_and_scale_invariant_for_core_features() -> None:
    first = compute_market_dna(_context(scale=1.0), MARKET_DNA_V1)
    second = compute_market_dna(_context(scale=10.0), MARKET_DNA_V1)
    core_codes = [
        "normalized_endpoint_return",
        "path_length",
        "linear_regression_slope",
        "return_mean",
        "return_std",
        "normalized_atr",
        "body_to_range_mean",
    ]

    for code in core_codes:
        assert first.availability[code] == AVAILABLE
        assert second.availability[code] == AVAILABLE
        assert first.feature_values[code] == pytest.approx(second.feature_values[code], rel=1e-12, abs=1e-12)

    payload = {"values": first.feature_values, "availability": first.availability}
    assert feature_vector_hash(payload) == feature_vector_hash(payload)


def test_missing_volume_features_are_unavailable_without_breaking_vector() -> None:
    result = compute_market_dna(_context(volume=np.zeros(64)), MARKET_DNA_V1)

    assert result.feature_values["relative_volume_mean"] is None
    assert result.availability["relative_volume_mean"] == "UNAVAILABLE_MISSING_CHANNEL"
    assert result.availability["normalized_endpoint_return"] == AVAILABLE
