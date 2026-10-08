from __future__ import annotations

import math
import time
from bisect import bisect_left, bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from itertools import pairwise
from typing import Any

import numpy as np
from market_genome_domain.models import (
    FeatureBuild,
    FeatureBuildStatus,
    MarketDNA,
    NormalizedPattern,
    PatternWindow,
    PriceBar,
)
from market_genome_normalization.service import representation_hash
from market_genome_shared.hashing import sha256_canonical
from market_genome_window_engine.service import source_data_hash
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from market_genome_features.definitions import FeatureSetDefinition, get_feature_set

AVAILABLE = "AVAILABLE"
UNAVAILABLE_MISSING_CHANNEL = "UNAVAILABLE_MISSING_CHANNEL"
UNAVAILABLE_INSUFFICIENT_BARS = "UNAVAILABLE_INSUFFICIENT_BARS"
UNAVAILABLE_ZERO_VARIANCE = "UNAVAILABLE_ZERO_VARIANCE"
UNAVAILABLE_NUMERICAL_FAILURE = "UNAVAILABLE_NUMERICAL_FAILURE"
UNAVAILABLE_INVALID_INPUT = "UNAVAILABLE_INVALID_INPUT"


class FeatureQualityFlag(str, Enum):
    none = "NONE"
    source_window_hash_mismatch = "SOURCE_WINDOW_HASH_MISMATCH"
    source_representation_hash_mismatch = "SOURCE_REPRESENTATION_HASH_MISMATCH"
    missing_volume = "MISSING_VOLUME"
    zero_variance = "ZERO_VARIANCE"
    numerical_failure = "NUMERICAL_FAILURE"


@dataclass
class FeatureContext:
    normalized_close: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray | None

    @classmethod
    def from_inputs(cls, bars: list[PriceBar], normalized_values: dict[str, Any]) -> FeatureContext:
        return cls(
            normalized_close=np.asarray(normalized_values.get("close", []), dtype=np.float64),
            open=np.asarray([float(bar.open) for bar in bars], dtype=np.float64),
            high=np.asarray([float(bar.high) for bar in bars], dtype=np.float64),
            low=np.asarray([float(bar.low) for bar in bars], dtype=np.float64),
            close=np.asarray([float(bar.close) for bar in bars], dtype=np.float64),
            volume=np.asarray([float(bar.volume) for bar in bars], dtype=np.float64) if bars else None,
        )

    @property
    def returns(self) -> np.ndarray:
        if len(self.close) < 2 or np.any(self.close <= 0):
            return np.asarray([], dtype=np.float64)
        return np.diff(np.log(self.close))


@dataclass
class ComputedFeatureSet:
    feature_values: dict[str, float | int | None]
    availability: dict[str, str]
    diagnostics: dict[str, Any]
    quality_flags: list[str]


@dataclass
class FeatureBuildResult:
    build: FeatureBuild
    source_pattern_count: int = 0
    created_features: int = 0
    existing_features: int = 0
    skipped_features: int = 0
    failed_features: int = 0
    elapsed_seconds: float | None = None
    errors: list[str] = field(default_factory=list)


def feature_configuration_hash(configuration: dict[str, Any]) -> str:
    return sha256_canonical(configuration)


def feature_vector_hash(payload: dict[str, Any]) -> str:
    return sha256_canonical(payload)


def _finite(values: np.ndarray) -> bool:
    return len(values) > 0 and bool(np.all(np.isfinite(values)))


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if not math.isfinite(numerator) or not math.isfinite(denominator) or abs(denominator) < 1e-12:
        return None
    return float(numerator / denominator)


def _returns(ctx: FeatureContext, minimum: int = 1) -> np.ndarray:
    values = ctx.returns
    if len(values) < minimum or not _finite(values):
        raise ValueError(UNAVAILABLE_INSUFFICIENT_BARS)
    return values


def _norm(ctx: FeatureContext, minimum: int = 2) -> np.ndarray:
    values = ctx.normalized_close
    if len(values) < minimum or not _finite(values):
        raise ValueError(UNAVAILABLE_INSUFFICIENT_BARS)
    return values


def _std(values: np.ndarray) -> float:
    return float(np.std(values, ddof=0))


def _autocorr(values: np.ndarray, lag: int) -> float:
    if len(values) <= lag:
        raise ValueError(UNAVAILABLE_INSUFFICIENT_BARS)
    left, right = values[:-lag], values[lag:]
    if _std(left) < 1e-12 or _std(right) < 1e-12:
        raise ValueError(UNAVAILABLE_ZERO_VARIANCE)
    return float(np.corrcoef(left, right)[0, 1])


def _linear_fit(y: np.ndarray) -> tuple[float, float, float, np.ndarray]:
    x = np.linspace(0.0, 1.0, len(y), dtype=np.float64)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    residuals = y - fitted
    total = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 if total < 1e-12 else 1.0 - float(np.sum(residuals**2)) / total
    return float(slope), float(intercept), float(r_squared), residuals


def _max_drawdown(y: np.ndarray) -> float:
    peaks = np.maximum.accumulate(y)
    return float(np.max(peaks - y))


def _max_runup(y: np.ndarray) -> float:
    troughs = np.minimum.accumulate(y)
    return float(np.max(y - troughs))


def _true_ranges(ctx: FeatureContext) -> np.ndarray:
    if len(ctx.close) < 2:
        raise ValueError(UNAVAILABLE_INSUFFICIENT_BARS)
    previous_close = np.concatenate(([ctx.close[0]], ctx.close[:-1]))
    return np.maximum(ctx.high - ctx.low, np.maximum(np.abs(ctx.high - previous_close), np.abs(ctx.low - previous_close)))


def _skewness(x: np.ndarray) -> float:
    sd = _std(x)
    if sd < 1e-12:
        raise ValueError(UNAVAILABLE_ZERO_VARIANCE)
    centered = x - np.mean(x)
    return float(np.mean(centered**3) / sd**3)


def _kurtosis(x: np.ndarray) -> float:
    sd = _std(x)
    if sd < 1e-12:
        raise ValueError(UNAVAILABLE_ZERO_VARIANCE)
    centered = x - np.mean(x)
    return float(np.mean(centered**4) / sd**4)


def _hurst_rs(x: np.ndarray) -> float:
    if len(x) < 16:
        raise ValueError(UNAVAILABLE_INSUFFICIENT_BARS)
    sizes = [s for s in (8, 16, 32) if s <= len(x)]
    rs_values: list[tuple[float, float]] = []
    for size in sizes:
        chunks = len(x) // size
        chunk_rs = []
        for idx in range(chunks):
            sample = x[idx * size : (idx + 1) * size]
            sd = _std(sample)
            if sd < 1e-12:
                continue
            cumulative = np.cumsum(sample - np.mean(sample))
            chunk_rs.append(float((np.max(cumulative) - np.min(cumulative)) / sd))
        if chunk_rs:
            rs_values.append((math.log(size), math.log(float(np.mean(chunk_rs)))))
    if len(rs_values) < 2:
        raise ValueError(UNAVAILABLE_ZERO_VARIANCE)
    return float(np.polyfit([p[0] for p in rs_values], [p[1] for p in rs_values], 1)[0])


def _variance_ratio(x: np.ndarray, lag: int) -> float:
    if len(x) <= lag:
        raise ValueError(UNAVAILABLE_INSUFFICIENT_BARS)
    var1 = float(np.var(x, ddof=0))
    if var1 < 1e-12:
        raise ValueError(UNAVAILABLE_ZERO_VARIANCE)
    aggregated = np.asarray([np.sum(x[i : i + lag]) for i in range(len(x) - lag + 1)], dtype=np.float64)
    return float(np.var(aggregated, ddof=0) / (lag * var1))


def _permutation_entropy(y: np.ndarray, dimension: int = 3, delay: int = 1) -> float:
    n = len(y) - delay * (dimension - 1)
    if n < 2:
        raise ValueError(UNAVAILABLE_INSUFFICIENT_BARS)
    patterns: dict[tuple[int, ...], int] = {}
    for idx in range(n):
        window = y[idx : idx + delay * dimension : delay]
        pattern = tuple(np.argsort(window, kind="stable"))
        patterns[pattern] = patterns.get(pattern, 0) + 1
    probs = np.asarray(list(patterns.values()), dtype=np.float64) / n
    entropy = -float(np.sum(probs * np.log(probs)))
    return float(entropy / math.log(math.factorial(dimension)))


def _sample_entropy(x: np.ndarray, m: int = 2, r_multiplier: float = 0.2) -> float:
    if len(x) < 16:
        raise ValueError(UNAVAILABLE_INSUFFICIENT_BARS)
    sd = _std(x)
    if sd < 1e-12:
        raise ValueError(UNAVAILABLE_ZERO_VARIANCE)
    radius = r_multiplier * sd

    def count_matches(order: int) -> int:
        count = 0
        templates = [x[i : i + order] for i in range(len(x) - order + 1)]
        for i, a in enumerate(templates):
            for b in templates[i + 1 :]:
                if float(np.max(np.abs(a - b))) <= radius:
                    count += 1
        return count

    b_count = count_matches(m)
    a_count = count_matches(m + 1)
    if a_count == 0 or b_count == 0:
        raise ValueError(UNAVAILABLE_NUMERICAL_FAILURE)
    return float(-math.log(a_count / b_count))


def _higuchi_fd(y: np.ndarray, k_max: int = 6) -> float:
    if len(y) < 16:
        raise ValueError(UNAVAILABLE_INSUFFICIENT_BARS)
    lengths: list[float] = []
    ks: list[float] = []
    n = len(y)
    for k in range(1, min(k_max, n // 2) + 1):
        lm = []
        for m in range(k):
            idxs = np.arange(m, n, k)
            if len(idxs) < 2:
                continue
            diffs = np.abs(np.diff(y[idxs]))
            norm = (n - 1) / ((len(idxs) - 1) * k)
            lm.append(float(np.sum(diffs) * norm / k))
        if lm and np.mean(lm) > 0:
            lengths.append(math.log(float(np.mean(lm))))
            ks.append(math.log(1.0 / k))
    if len(lengths) < 2:
        raise ValueError(UNAVAILABLE_NUMERICAL_FAILURE)
    return float(np.polyfit(ks, lengths, 1)[0])


def _turning_points(y: np.ndarray) -> int:
    if len(y) < 3:
        raise ValueError(UNAVAILABLE_INSUFFICIENT_BARS)
    diff = np.diff(y)
    signs = np.sign(diff[np.abs(diff) > 1e-12])
    if len(signs) < 2:
        return 0
    return int(np.sum(signs[1:] != signs[:-1]))


def _extrema(y: np.ndarray) -> list[int]:
    if len(y) < 3:
        raise ValueError(UNAVAILABLE_INSUFFICIENT_BARS)
    points = [0]
    for idx in range(1, len(y) - 1):
        if (y[idx] >= y[idx - 1] and y[idx] > y[idx + 1]) or (y[idx] <= y[idx - 1] and y[idx] < y[idx + 1]):
            points.append(idx)
    points.append(len(y) - 1)
    return sorted(set(points))


def _swing_sizes(y: np.ndarray) -> tuple[np.ndarray, np.ndarray, list[int]]:
    points = _extrema(y)
    if len(points) < 2:
        return np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64), points
    sizes = np.asarray([abs(float(y[b] - y[a])) for a, b in pairwise(points)], dtype=np.float64)
    durations = np.asarray([b - a for a, b in pairwise(points)], dtype=np.float64)
    return sizes, durations, points


def _volume(ctx: FeatureContext) -> np.ndarray:
    if ctx.volume is None or not _finite(ctx.volume) or len(ctx.volume) < 2 or np.mean(ctx.volume) <= 0:
        raise ValueError(UNAVAILABLE_MISSING_CHANNEL)
    return ctx.volume


def _half(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mid = len(values) // 2
    if mid == 0 or mid == len(values):
        raise ValueError(UNAVAILABLE_INSUFFICIENT_BARS)
    return values[:mid], values[mid:]


def _bar_range(ctx: FeatureContext) -> np.ndarray:
    ranges = ctx.high - ctx.low
    if len(ranges) == 0 or np.any(ranges <= 0):
        raise ValueError(UNAVAILABLE_INVALID_INPUT)
    return ranges


def _body_to_range(ctx: FeatureContext) -> np.ndarray:
    return np.abs(ctx.close - ctx.open) / _bar_range(ctx)


def _volume_return_corr(ctx: FeatureContext) -> float:
    volume = _volume(ctx)
    returns = np.abs(_returns(ctx))
    aligned = volume[1:]
    if len(aligned) != len(returns) or _std(aligned) < 1e-12 or _std(returns) < 1e-12:
        raise ValueError(UNAVAILABLE_ZERO_VARIANCE)
    return float(np.corrcoef(aligned, returns)[0, 1])


def _higher_lower_counts(y: np.ndarray) -> dict[str, int]:
    points = _extrema(y)
    highs: list[float] = []
    lows: list[float] = []
    for idx in points[1:-1]:
        if y[idx] >= y[idx - 1] and y[idx] > y[idx + 1]:
            highs.append(float(y[idx]))
        elif y[idx] <= y[idx - 1] and y[idx] < y[idx + 1]:
            lows.append(float(y[idx]))
    return {
        "higher_high": int(sum(1 for a, b in pairwise(highs) if b > a)),
        "lower_high": int(sum(1 for a, b in pairwise(highs) if b < a)),
        "higher_low": int(sum(1 for a, b in pairwise(lows) if b > a)),
        "lower_low": int(sum(1 for a, b in pairwise(lows) if b < a)),
    }


def _feature_map() -> dict[str, Callable[[FeatureContext], float | int]]:
    return {
        "normalized_endpoint_return": lambda c: float(_norm(c)[-1] - _norm(c)[0]),
        "path_displacement": lambda c: abs(float(_norm(c)[-1] - _norm(c)[0])),
        "path_length": lambda c: float(np.sum(np.abs(np.diff(_norm(c))))),
        "path_efficiency_ratio": lambda c: _safe_ratio(abs(float(_norm(c)[-1] - _norm(c)[0])), float(np.sum(np.abs(np.diff(_norm(c)))))) or 0.0,
        "maximum_drawdown_normalized": lambda c: _max_drawdown(_norm(c)),
        "maximum_runup_normalized": lambda c: _max_runup(_norm(c)),
        "endpoint_position_in_range": lambda c: _safe_ratio(float(_norm(c)[-1] - np.min(_norm(c))), float(np.max(_norm(c)) - np.min(_norm(c)))) or 0.0,
        "linear_regression_slope": lambda c: _linear_fit(_norm(c))[0],
        "linear_regression_intercept": lambda c: _linear_fit(_norm(c))[1],
        "linear_regression_r_squared": lambda c: _linear_fit(_norm(c))[2],
        "linear_regression_residual_std": lambda c: _std(_linear_fit(_norm(c))[3]),
        "trend_direction_consistency": lambda c: abs(float(np.mean(np.sign(np.diff(_norm(c)))))),
        "lsma_endpoint": lambda c: float((_linear_fit(_norm(c))[0] * 1.0) + _linear_fit(_norm(c))[1]),
        "lsma_slope": lambda c: _linear_fit(_norm(c))[0],
        "curvature_quadratic": lambda c: float(np.polyfit(np.linspace(0, 1, len(_norm(c))), _norm(c), 2)[0]) if len(_norm(c)) >= 3 else 0.0,
        "return_mean": lambda c: float(np.mean(_returns(c))),
        "return_std": lambda c: _std(_returns(c)),
        "positive_return_ratio": lambda c: float(np.mean(_returns(c) > 0)),
        "negative_return_ratio": lambda c: float(np.mean(_returns(c) < 0)),
        "momentum_first_half": lambda c: float(np.sum(_half(_returns(c))[0])),
        "momentum_second_half": lambda c: float(np.sum(_half(_returns(c))[1])),
        "momentum_acceleration": lambda c: float(np.sum(_half(_returns(c))[1]) - np.sum(_half(_returns(c))[0])),
        "lag_1_autocorrelation": lambda c: _autocorr(_returns(c, 3), 1),
        "lag_2_autocorrelation": lambda c: _autocorr(_returns(c, 4), 2),
        "ar_1_coefficient": lambda c: _autocorr(_returns(c, 3), 1),
        "realized_volatility": lambda c: _std(_returns(c)),
        "downside_volatility": lambda c: _std(_returns(c)[_returns(c) < 0]) if np.any(_returns(c) < 0) else 0.0,
        "upside_volatility": lambda c: _std(_returns(c)[_returns(c) > 0]) if np.any(_returns(c) > 0) else 0.0,
        "volatility_asymmetry": lambda c: float((_std(_returns(c)[_returns(c) > 0]) if np.any(_returns(c) > 0) else 0.0) - (_std(_returns(c)[_returns(c) < 0]) if np.any(_returns(c) < 0) else 0.0)),
        "normalized_atr": lambda c: _safe_ratio(float(np.mean(_true_ranges(c))), float(np.mean(c.close))) or 0.0,
        "volatility_first_half": lambda c: _std(_half(_returns(c))[0]),
        "volatility_second_half": lambda c: _std(_half(_returns(c))[1]),
        "volatility_expansion_ratio": lambda c: _safe_ratio(_std(_half(_returns(c))[1]), _std(_half(_returns(c))[0])) or 0.0,
        "range_expansion_ratio": lambda c: _safe_ratio(float(np.ptp(_norm(c)[len(_norm(c)) // 2 :])), float(np.ptp(_norm(c)[: len(_norm(c)) // 2]))) or 0.0,
        "return_skewness": lambda c: _skewness(_returns(c)),
        "return_kurtosis": lambda c: _kurtosis(_returns(c)),
        "return_median": lambda c: float(np.median(_returns(c))),
        "return_mad": lambda c: float(np.median(np.abs(_returns(c) - np.median(_returns(c))))),
        "upper_tail_ratio": lambda c: _safe_ratio(float(np.percentile(_returns(c), 95)), _std(_returns(c))) or 0.0,
        "lower_tail_ratio": lambda c: _safe_ratio(abs(float(np.percentile(_returns(c), 5))), _std(_returns(c))) or 0.0,
        "maximum_positive_return": lambda c: float(np.max(_returns(c))),
        "maximum_negative_return": lambda c: float(np.min(_returns(c))),
        "hurst_rs_v1": lambda c: _hurst_rs(_returns(c, 16)),
        "variance_ratio_2": lambda c: _variance_ratio(_returns(c, 3), 2),
        "variance_ratio_4": lambda c: _variance_ratio(_returns(c, 5), 4),
        "permutation_entropy": lambda c: _permutation_entropy(_norm(c), 3, 1),
        "sample_entropy": lambda c: _sample_entropy(_norm(c)),
        "higuchi_fractal_dimension": lambda c: _higuchi_fd(_norm(c)),
        "turning_point_count": lambda c: _turning_points(_norm(c)),
        "turning_point_density": lambda c: float(_turning_points(_norm(c)) / max(1, len(_norm(c)) - 2)),
        "swing_count": lambda c: len(_swing_sizes(_norm(c))[0]),
        "average_swing_size": lambda c: float(np.mean(_swing_sizes(_norm(c))[0])) if len(_swing_sizes(_norm(c))[0]) else 0.0,
        "median_swing_size": lambda c: float(np.median(_swing_sizes(_norm(c))[0])) if len(_swing_sizes(_norm(c))[0]) else 0.0,
        "average_swing_duration": lambda c: float(np.mean(_swing_sizes(_norm(c))[1])) if len(_swing_sizes(_norm(c))[1]) else 0.0,
        "maximum_swing_size": lambda c: float(np.max(_swing_sizes(_norm(c))[0])) if len(_swing_sizes(_norm(c))[0]) else 0.0,
        "impulse_pullback_ratio": lambda c: _safe_ratio(float(np.max(_swing_sizes(_norm(c))[0])), float(np.mean(_swing_sizes(_norm(c))[0]))) or 0.0,
        "higher_high_count": lambda c: _higher_lower_counts(_norm(c))["higher_high"],
        "lower_low_count": lambda c: _higher_lower_counts(_norm(c))["lower_low"],
        "higher_low_count": lambda c: _higher_lower_counts(_norm(c))["higher_low"],
        "lower_high_count": lambda c: _higher_lower_counts(_norm(c))["lower_high"],
        "body_to_range_mean": lambda c: float(np.mean(_body_to_range(c))),
        "body_to_range_std": lambda c: _std(_body_to_range(c)),
        "upper_wick_ratio_mean": lambda c: float(np.mean((c.high - np.maximum(c.open, c.close)) / _bar_range(c))),
        "lower_wick_ratio_mean": lambda c: float(np.mean((np.minimum(c.open, c.close) - c.low) / _bar_range(c))),
        "bullish_candle_ratio": lambda c: float(np.mean(c.close > c.open)),
        "bearish_candle_ratio": lambda c: float(np.mean(c.close < c.open)),
        "inside_bar_ratio": lambda c: float(np.mean((c.high[1:] <= c.high[:-1]) & (c.low[1:] >= c.low[:-1]))) if len(c.high) > 1 else 0.0,
        "outside_bar_ratio": lambda c: float(np.mean((c.high[1:] >= c.high[:-1]) & (c.low[1:] <= c.low[:-1]))) if len(c.high) > 1 else 0.0,
        "close_location_value_mean": lambda c: float(np.mean((c.close - c.low) / _bar_range(c))),
        "relative_volume_mean": lambda c: float(np.mean(_volume(c) / np.mean(_volume(c)))),
        "volume_coefficient_of_variation": lambda c: _safe_ratio(_std(_volume(c)), float(np.mean(_volume(c)))) or 0.0,
        "volume_trend_slope": lambda c: _linear_fit(_volume(c) / np.mean(_volume(c)))[0],
        "volume_absolute_return_correlation": lambda c: _volume_return_corr(c),
        "volume_expansion_ratio": lambda c: _safe_ratio(float(np.mean(_half(_volume(c))[1])), float(np.mean(_half(_volume(c))[0]))) or 0.0,
        "high_volume_location": lambda c: float(int(np.argmax(_volume(c))) / max(1, len(_volume(c)) - 1)),
    }


def compute_market_dna(context: FeatureContext, feature_set: FeatureSetDefinition) -> ComputedFeatureSet:
    calculators = _feature_map()
    values: dict[str, float | int | None] = {}
    availability: dict[str, str] = {}
    unavailable_reasons: dict[str, int] = {}
    flags: set[str] = set()
    for code in feature_set.ordered_feature_codes:
        try:
            value = calculators[code](context)
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(UNAVAILABLE_NUMERICAL_FAILURE)
            values[code] = float(value) if isinstance(value, np.floating) else value
            availability[code] = AVAILABLE
        except ValueError as exc:
            reason = str(exc) if str(exc).startswith("UNAVAILABLE_") else UNAVAILABLE_NUMERICAL_FAILURE
            values[code] = None
            availability[code] = reason
            unavailable_reasons[reason] = unavailable_reasons.get(reason, 0) + 1
            if reason == UNAVAILABLE_MISSING_CHANNEL:
                flags.add(FeatureQualityFlag.missing_volume.value)
            elif reason == UNAVAILABLE_ZERO_VARIANCE:
                flags.add(FeatureQualityFlag.zero_variance.value)
            else:
                flags.add(FeatureQualityFlag.numerical_failure.value)
        except (FloatingPointError, IndexError, KeyError, OverflowError, ZeroDivisionError):
            values[code] = None
            availability[code] = UNAVAILABLE_NUMERICAL_FAILURE
            unavailable_reasons[UNAVAILABLE_NUMERICAL_FAILURE] = unavailable_reasons.get(UNAVAILABLE_NUMERICAL_FAILURE, 0) + 1
            flags.add(FeatureQualityFlag.numerical_failure.value)
    available = sum(1 for status in availability.values() if status == AVAILABLE)
    diagnostics = {
        "feature_set_code": feature_set.code,
        "feature_set_version": feature_set.version,
        "feature_count": len(feature_set.ordered_feature_codes),
        "available_feature_count": available,
        "unavailable_feature_count": len(feature_set.ordered_feature_codes) - available,
        "unavailable_reasons": unavailable_reasons,
        "input": {"raw_bar_count": len(context.close), "normalized_point_count": len(context.normalized_close)},
    }
    return ComputedFeatureSet(values, availability, diagnostics, sorted(flags) or [FeatureQualityFlag.none.value])


class FeatureBuildService:
    def __init__(self, session: Session):
        self.session = session
        self._bar_cache: dict[tuple[str, str], tuple[list[datetime], list[PriceBar]]] = {}

    def build(
        self,
        feature_set_code: str = "market_dna_v1",
        mode: str = "incremental",
        instrument_id: str | None = None,
        timeframe_id: str | None = None,
        window_length: int | None = None,
        start_timestamp: datetime | None = None,
        end_timestamp: datetime | None = None,
    ) -> FeatureBuildResult:
        started = time.monotonic()
        if mode not in {"full", "incremental", "range"}:
            raise ValueError("FEATURE_BUILD_CONFIGURATION_INVALID")
        feature_set = get_feature_set(feature_set_code)
        configuration = {
            "feature_set_code": feature_set.code,
            "feature_set_version": feature_set.version,
            "feature_set_configuration": feature_set.configuration,
            "source_normalization_method": feature_set.required_normalization_method,
            "source_normalization_version": feature_set.required_normalization_version,
            "source_resampling_method": feature_set.required_resampling_method,
            "source_resample_points": feature_set.required_resample_points,
            "instrument_id": instrument_id,
            "timeframe_id": timeframe_id,
            "window_length": window_length,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
        }
        config_hash = feature_configuration_hash(configuration)
        build = FeatureBuild(
            feature_set_code=feature_set.code,
            feature_set_version=feature_set.version,
            source_normalization_method=feature_set.required_normalization_method,
            source_normalization_version=feature_set.required_normalization_version,
            source_resampling_method=feature_set.required_resampling_method,
            source_resample_points=feature_set.required_resample_points,
            instrument_id=instrument_id,
            timeframe_id=timeframe_id,
            window_length=window_length,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            mode=mode,
            configuration=configuration,
            configuration_hash=config_hash,
            status=FeatureBuildStatus.running.value,
            started_at=datetime.now(UTC),
        )
        self.session.add(build)
        self.session.flush()
        result = FeatureBuildResult(build=build)
        try:
            patterns = self._select_patterns(feature_set, instrument_id, timeframe_id, window_length, start_timestamp, end_timestamp)
            result.source_pattern_count = len(patterns)
            existing = self._existing_keys(feature_set, config_hash)
            for pattern in patterns:
                window = pattern.pattern_window
                key = (window.id, pattern.id, feature_set.code, feature_set.version, config_hash, pattern.source_window_hash, pattern.representation_hash)
                if mode == "incremental" and key in existing:
                    result.existing_features += 1
                    continue
                try:
                    if pattern.source_window_hash != window.source_data_hash:
                        raise ValueError("FEATURE_SOURCE_WINDOW_HASH_MISMATCH")
                    calculated_representation_hash = representation_hash(
                        {
                            "channel_schema": pattern.channel_schema,
                            "values": pattern.normalized_values,
                            "method": pattern.normalization_method,
                            "version": pattern.normalization_version,
                            "resampling_method": pattern.resampling_method,
                            "resample_points": pattern.resample_points,
                            "precision": pattern.diagnostics.get("storage_precision", 12),
                            "source_window_hash": pattern.source_window_hash,
                            "configuration_hash": pattern.configuration_hash,
                        }
                    )
                    if calculated_representation_hash != pattern.representation_hash:
                        raise ValueError("FEATURE_SOURCE_REPRESENTATION_HASH_MISMATCH")
                    bars = self._window_bars(window)
                    if source_data_hash(bars) != window.source_data_hash:
                        raise ValueError("FEATURE_SOURCE_WINDOW_HASH_MISMATCH")
                    computed = compute_market_dna(FeatureContext.from_inputs(bars, pattern.normalized_values), feature_set)
                    vector = {
                        "ordered_features": feature_set.ordered_feature_codes,
                        "values": [computed.feature_values[code] for code in feature_set.ordered_feature_codes],
                        "availability_mask": [computed.availability[code] == AVAILABLE for code in feature_set.ordered_feature_codes],
                    }
                    vector_hash = feature_vector_hash(
                        {
                            "feature_set_code": feature_set.code,
                            "feature_set_version": feature_set.version,
                            "configuration_hash": config_hash,
                            "source_window_hash": pattern.source_window_hash,
                            "source_representation_hash": pattern.representation_hash,
                            "feature_vector": vector,
                            "availability": computed.availability,
                        }
                    )
                    if key in existing:
                        result.existing_features += 1
                        continue
                    available = computed.diagnostics["available_feature_count"]
                    self.session.add(
                        MarketDNA(
                            pattern_window_id=window.id,
                            normalized_pattern_id=pattern.id,
                            feature_set_code=feature_set.code,
                            feature_set_version=feature_set.version,
                            source_window_hash=pattern.source_window_hash,
                            source_representation_hash=pattern.representation_hash,
                            configuration_hash=config_hash,
                            feature_vector_hash=vector_hash,
                            feature_count=len(feature_set.ordered_feature_codes),
                            available_feature_count=available,
                            unavailable_feature_count=len(feature_set.ordered_feature_codes) - available,
                            feature_vector=vector,
                            feature_values=computed.feature_values,
                            availability=computed.availability,
                            diagnostics=computed.diagnostics
                            | {"source_window_hash_verified": True, "source_representation_hash_verified": True},
                            quality_flags=computed.quality_flags,
                        )
                    )
                    existing.add(key)
                    result.created_features += 1
                except ValueError as exc:
                    result.failed_features += 1
                    result.errors.append(str(exc))
            result.elapsed_seconds = round(time.monotonic() - started, 3)
            build.source_pattern_count = result.source_pattern_count
            build.created_feature_count = result.created_features
            build.existing_feature_count = result.existing_features
            build.skipped_feature_count = result.skipped_features
            build.failed_feature_count = result.failed_features
            build.status = FeatureBuildStatus.completed_with_warnings.value if result.failed_features else FeatureBuildStatus.completed.value
            build.error_message = "; ".join(result.errors[:5]) or None
            build.completed_at = datetime.now(UTC)
            build.elapsed_seconds = result.elapsed_seconds
            self.session.commit()
            self.session.refresh(build)
            return result
        except Exception as exc:
            build.status = FeatureBuildStatus.failed.value
            build.error_message = str(exc)
            build.completed_at = datetime.now(UTC)
            build.elapsed_seconds = round(time.monotonic() - started, 3)
            self.session.commit()
            raise

    def _select_patterns(
        self,
        feature_set: FeatureSetDefinition,
        instrument_id: str | None,
        timeframe_id: str | None,
        window_length: int | None,
        start_timestamp: datetime | None,
        end_timestamp: datetime | None,
    ) -> list[NormalizedPattern]:
        query = (
            select(NormalizedPattern)
            .join(PatternWindow, PatternWindow.id == NormalizedPattern.pattern_window_id)
            .options(selectinload(NormalizedPattern.pattern_window))
            .where(
                NormalizedPattern.normalization_method == feature_set.required_normalization_method,
                NormalizedPattern.normalization_version == feature_set.required_normalization_version,
                NormalizedPattern.resampling_method == feature_set.required_resampling_method,
                NormalizedPattern.resample_points == feature_set.required_resample_points,
            )
        )
        if instrument_id:
            query = query.where(PatternWindow.instrument_id == instrument_id)
        if timeframe_id:
            query = query.where(PatternWindow.timeframe_id == timeframe_id)
        if window_length:
            query = query.where(PatternWindow.window_length == window_length)
        if start_timestamp:
            query = query.where(PatternWindow.end_timestamp >= start_timestamp)
        if end_timestamp:
            query = query.where(PatternWindow.end_timestamp <= end_timestamp)
        return list(self.session.scalars(query.order_by(PatternWindow.end_timestamp, NormalizedPattern.id)))

    def _window_bars(self, window: PatternWindow) -> list[PriceBar]:
        key = (window.instrument_id, window.timeframe_id)
        if key not in self._bar_cache:
            bars = list(
                self.session.scalars(
                    select(PriceBar)
                    .where(PriceBar.instrument_id == window.instrument_id, PriceBar.timeframe_id == window.timeframe_id)
                    .order_by(PriceBar.timestamp, PriceBar.id)
                )
            )
            self._bar_cache[key] = ([bar.timestamp for bar in bars], bars)
        timestamps, bars = self._bar_cache[key]
        left = bisect_left(timestamps, window.start_timestamp)
        right = bisect_right(timestamps, window.end_timestamp)
        return bars[left:right]

    def _existing_keys(self, feature_set: FeatureSetDefinition, configuration_hash: str) -> set[tuple[Any, ...]]:
        rows = self.session.execute(
            select(
                MarketDNA.pattern_window_id,
                MarketDNA.normalized_pattern_id,
                MarketDNA.feature_set_code,
                MarketDNA.feature_set_version,
                MarketDNA.configuration_hash,
                MarketDNA.source_window_hash,
                MarketDNA.source_representation_hash,
            ).where(
                MarketDNA.feature_set_code == feature_set.code,
                MarketDNA.feature_set_version == feature_set.version,
                MarketDNA.configuration_hash == configuration_hash,
            )
        )
        return {tuple(row) for row in rows}
