from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureDefinition:
    code: str
    label: str
    version: str
    description: str
    feature_group: str
    input_source: str
    required_channels: list[str]
    minimum_bars: int
    output_type: str = "float"
    is_scale_invariant: bool = True
    is_translation_invariant: bool = False
    expected_range: str | None = None
    missing_value_policy: str = "mark_unavailable"
    numerical_stability_notes: str = "Finite inputs required; unstable denominators are unavailable."
    formula_reference: str = "docs/research/feature-catalog.md"


MARKET_DNA_V1_FEATURES = [
    "normalized_endpoint_return", "path_displacement", "path_length", "path_efficiency_ratio",
    "maximum_drawdown_normalized", "maximum_runup_normalized", "endpoint_position_in_range",
    "linear_regression_slope", "linear_regression_intercept", "linear_regression_r_squared",
    "linear_regression_residual_std", "trend_direction_consistency", "lsma_endpoint",
    "lsma_slope", "curvature_quadratic",
    "return_mean", "return_std", "positive_return_ratio", "negative_return_ratio",
    "momentum_first_half", "momentum_second_half", "momentum_acceleration",
    "lag_1_autocorrelation", "lag_2_autocorrelation", "ar_1_coefficient",
    "realized_volatility", "downside_volatility", "upside_volatility", "volatility_asymmetry",
    "normalized_atr", "volatility_first_half", "volatility_second_half",
    "volatility_expansion_ratio", "range_expansion_ratio",
    "return_skewness", "return_kurtosis", "return_median", "return_mad",
    "upper_tail_ratio", "lower_tail_ratio", "maximum_positive_return", "maximum_negative_return",
    "hurst_rs_v1", "variance_ratio_2", "variance_ratio_4",
    "permutation_entropy", "sample_entropy", "higuchi_fractal_dimension",
    "turning_point_count", "turning_point_density",
    "swing_count", "average_swing_size", "median_swing_size", "average_swing_duration",
    "maximum_swing_size", "impulse_pullback_ratio", "higher_high_count", "lower_low_count",
    "higher_low_count", "lower_high_count",
    "body_to_range_mean", "body_to_range_std", "upper_wick_ratio_mean", "lower_wick_ratio_mean",
    "bullish_candle_ratio", "bearish_candle_ratio", "inside_bar_ratio", "outside_bar_ratio",
    "close_location_value_mean",
    "relative_volume_mean", "volume_coefficient_of_variation", "volume_trend_slope",
    "volume_absolute_return_correlation", "volume_expansion_ratio", "high_volume_location",
]


def _group(code: str) -> str:
    if code.startswith(("normalized_", "path_", "maximum_drawdown", "maximum_runup", "endpoint_")):
        return "PATH"
    if code.startswith(("linear_", "trend_", "lsma_", "curvature_")):
        return "TREND"
    if code.startswith(("return_", "positive_", "negative_", "momentum_", "lag_", "ar_")):
        return "MOMENTUM"
    if code.startswith(("realized_", "downside_", "upside_", "volatility_", "normalized_atr", "range_expansion")):
        return "VOLATILITY"
    if code in {"return_skewness", "return_kurtosis", "return_median", "return_mad", "upper_tail_ratio", "lower_tail_ratio", "maximum_positive_return", "maximum_negative_return"}:
        return "DISTRIBUTION"
    if code.startswith(("hurst_", "variance_ratio")):
        return "PERSISTENCE"
    if code in {"permutation_entropy", "sample_entropy", "higuchi_fractal_dimension", "turning_point_count", "turning_point_density"}:
        return "COMPLEXITY"
    if code.startswith(("swing_", "average_swing", "median_swing", "maximum_swing", "impulse_", "higher_", "lower_")):
        return "STRUCTURE"
    if code.endswith(("_candle_ratio", "_bar_ratio")) or "wick" in code or "body_to_range" in code or code == "close_location_value_mean":
        return "CANDLE"
    if code.startswith(("relative_volume", "volume_", "high_volume")):
        return "VOLUME"
    return "PATH"


def _input_source(group: str) -> str:
    if group in {"CANDLE", "VOLUME", "VOLATILITY", "MOMENTUM", "DISTRIBUTION"}:
        return "RAW_BARS"
    return "NORMALIZED_CLOSE"


FEATURE_DEFINITIONS: dict[str, FeatureDefinition] = {
    code: FeatureDefinition(
        code=code,
        label=code.replace("_", " ").title(),
        version="market_dna_v1",
        description=f"{code} in market_dna_v1.",
        feature_group=_group(code),
        input_source=_input_source(_group(code)),
        required_channels=["close"] if _group(code) not in {"CANDLE", "VOLUME"} else ["open", "high", "low", "close"],
        minimum_bars=8 if code not in {"hurst_rs_v1", "higuchi_fractal_dimension", "sample_entropy"} else 16,
        expected_range="[0, 1]" if code.endswith(("_ratio", "_density")) or code == "permutation_entropy" else None,
        is_translation_invariant=_group(code) in {"PATH", "TREND", "COMPLEXITY", "STRUCTURE"},
    )
    for code in MARKET_DNA_V1_FEATURES
}


@dataclass(frozen=True)
class FeatureSetDefinition:
    code: str
    version: str
    label: str
    description: str
    ordered_feature_codes: list[str]
    required_normalization_method: str
    required_normalization_version: str
    required_resampling_method: str
    required_resample_points: int
    configuration: dict


MARKET_DNA_V1 = FeatureSetDefinition(
    code="market_dna_v1",
    version="market_dna_v1",
    label="Market DNA v1",
    description="Initial interpretable handcrafted Market DNA feature vector.",
    ordered_feature_codes=MARKET_DNA_V1_FEATURES,
    required_normalization_method="anchored_log_return",
    required_normalization_version="normalization_v1",
    required_resampling_method="linear",
    required_resample_points=64,
    configuration={
        "returns": "log",
        "hurst": "rescaled_range_v1",
        "permutation_entropy": {"embedding_dimension": 3, "delay": 1},
        "sample_entropy": {"m": 2, "r_multiplier": 0.2},
        "higuchi": {"k_max": 6},
        "swing": {"method": "local_extrema_v1"},
    },
)

FEATURE_SETS = {MARKET_DNA_V1.code: MARKET_DNA_V1}


def list_feature_definitions() -> list[FeatureDefinition]:
    return [FEATURE_DEFINITIONS[code] for code in MARKET_DNA_V1_FEATURES]


def get_feature_definition(code: str) -> FeatureDefinition:
    try:
        return FEATURE_DEFINITIONS[code]
    except KeyError as exc:
        raise ValueError("FEATURE_DEFINITION_NOT_FOUND") from exc


def list_feature_sets() -> list[FeatureSetDefinition]:
    return list(FEATURE_SETS.values())


def get_feature_set(code: str) -> FeatureSetDefinition:
    try:
        return FEATURE_SETS[code]
    except KeyError as exc:
        raise ValueError("FEATURE_SET_NOT_FOUND") from exc
