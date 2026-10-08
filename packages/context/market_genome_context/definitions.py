from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DIMENSIONS = [
    "TREND",
    "VOLATILITY",
    "VOLATILITY_PHASE",
    "PERSISTENCE",
    "ACTIVITY",
    "SHOCK",
    "MARKET_PHASE",
    "MULTI_RESOLUTION",
]

DIMENSION_STATES = {
    "TREND": ["STRONG_UPTREND", "WEAK_UPTREND", "RANGE", "WEAK_DOWNTREND", "STRONG_DOWNTREND", "UNCERTAIN"],
    "VOLATILITY": ["VERY_LOW", "LOW", "NORMAL", "HIGH", "EXTREME", "UNCERTAIN"],
    "VOLATILITY_PHASE": ["COMPRESSING", "STABLE", "EXPANDING", "UNCERTAIN"],
    "PERSISTENCE": ["PERSISTENT", "NEUTRAL", "MEAN_REVERTING", "UNCERTAIN"],
    "ACTIVITY": ["LOW", "NORMAL", "ELEVATED", "UNAVAILABLE", "UNCERTAIN"],
    "SHOCK": ["NORMAL", "EVENT_LIKE", "DISCONTINUOUS", "UNCERTAIN"],
    "MARKET_PHASE": [
        "ACCUMULATION_LIKE",
        "MARKUP_LIKE",
        "DISTRIBUTION_LIKE",
        "MARKDOWN_LIKE",
        "BALANCED",
        "TRANSITION",
        "UNCERTAIN",
    ],
    "MULTI_RESOLUTION": [
        "ALIGNED_BULLISH",
        "ALIGNED_BEARISH",
        "ALIGNED_RANGE",
        "LOCAL_BULLISH_MACRO_BEARISH",
        "LOCAL_BEARISH_MACRO_BULLISH",
        "LOCAL_TREND_MACRO_RANGE",
        "LOCAL_RANGE_MACRO_TREND",
        "MIXED",
        "UNAVAILABLE",
        "UNCERTAIN",
    ],
}


TRANSPARENT_CONTEXT_V1_CONFIG: dict[str, Any] = {
    "context_producer_code": "transparent_context_v1",
    "context_producer_version": "transparent_context_v1",
    "source": {
        "feature_set_code": "market_dna_v1",
        "feature_set_version": "market_dna_v1",
        "normalization_method": "anchored_log_return",
        "normalization_version": "normalization_v1",
        "resampling_method": "linear",
        "resample_points": 64,
    },
    "threshold_mode": {"default": "absolute", "supported": ["absolute", "descriptive_reference_quantile"]},
    "trend": {
        "weak_slope_threshold": 0.03,
        "strong_slope_threshold": 0.10,
        "minimum_trend_r_squared": 0.35,
        "strong_trend_r_squared": 0.65,
        "minimum_efficiency_ratio": 0.35,
        "strong_efficiency_ratio": 0.60,
        "minimum_direction_consistency": 0.58,
        "strong_direction_consistency": 0.68,
        "minimum_displacement": 0.02,
    },
    "volatility": {"very_low_score_max": 0.20, "low_score_max": 0.40, "high_score_min": 0.70, "extreme_score_min": 0.90},
    "volatility_phase": {"compression_ratio_max": 0.75, "expansion_ratio_min": 1.33},
    "persistence": {
        "hurst_mean_reverting_max": 0.45,
        "hurst_persistent_min": 0.55,
        "ar1_mean_reverting_max": -0.10,
        "ar1_persistent_min": 0.10,
        "variance_ratio_mean_reverting_max": 0.90,
        "variance_ratio_persistent_min": 1.10,
    },
    "activity": {"low_score_max": 0.30, "elevated_score_min": 0.70, "missing_volume_state": "UNAVAILABLE"},
    "shock": {
        "event_largest_return_z": 3.0,
        "discontinuous_largest_return_z": 5.0,
        "event_tail_ratio": 3.0,
        "discontinuity_path_share": 0.35,
    },
    "market_phase": {"minimum_phase_confidence": 0.55},
    "multi_resolution": {
        "local_length": 16,
        "intermediate_length": 64,
        "macro_length": 256,
        "allow_nearest_available_length": True,
        "maximum_timestamp_distance_bars": 0,
    },
    "confidence": {"minimum_dimension_confidence": 0.55, "minimum_composite_confidence": 0.50},
    "composite_weights": {
        "trend": 0.22,
        "volatility": 0.16,
        "volatility_phase": 0.10,
        "persistence": 0.14,
        "activity": 0.08,
        "shock": 0.12,
        "market_phase": 0.10,
        "multi_resolution": 0.08,
    },
    "precision": {"calculation_dtype": "float64", "storage_decimals": 12},
}


@dataclass(frozen=True)
class ContextProducerDefinition:
    code: str
    version: str
    label: str
    description: str
    required_feature_set_code: str
    required_feature_set_version: str
    required_normalization_method: str
    required_normalization_version: str
    required_resampling_method: str
    required_resample_points: int
    dimensions: list[str]
    is_supervised: bool
    uses_future_outcomes: bool
    supports_multi_resolution: bool
    configuration_schema: dict[str, Any]


TRANSPARENT_CONTEXT_V1 = ContextProducerDefinition(
    code="transparent_context_v1",
    version="transparent_context_v1",
    label="Transparent Context v1",
    description="Rule-based, explainable market context classification from Market DNA.",
    required_feature_set_code="market_dna_v1",
    required_feature_set_version="market_dna_v1",
    required_normalization_method="anchored_log_return",
    required_normalization_version="normalization_v1",
    required_resampling_method="linear",
    required_resample_points=64,
    dimensions=DIMENSIONS,
    is_supervised=False,
    uses_future_outcomes=False,
    supports_multi_resolution=True,
    configuration_schema=TRANSPARENT_CONTEXT_V1_CONFIG,
)

PRODUCERS = {TRANSPARENT_CONTEXT_V1.code: TRANSPARENT_CONTEXT_V1}


def list_context_producers() -> list[ContextProducerDefinition]:
    return list(PRODUCERS.values())


def get_context_producer(code: str) -> ContextProducerDefinition:
    try:
        return PRODUCERS[code]
    except KeyError as exc:
        raise ValueError("CONTEXT_PRODUCER_NOT_FOUND") from exc


def list_context_dimensions() -> list[dict[str, Any]]:
    return [{"code": dimension, "states": DIMENSION_STATES[dimension], "version": "transparent_context_v1"} for dimension in DIMENSIONS]
