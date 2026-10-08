from __future__ import annotations

import math
import time
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import numpy as np
from market_genome_domain.models import (
    NormalizationBuild,
    NormalizationBuildStatus,
    NormalizedPattern,
    PatternWindow,
    PriceBar,
)
from market_genome_shared.hashing import sha256_canonical
from market_genome_window_engine.service import source_data_hash
from sqlalchemy import select
from sqlalchemy.orm import Session

from market_genome_normalization.methods import NormalizationMethodDefinition, get_method
from market_genome_normalization.resampling import resample_channels


class NormalizationQualityFlag(str, Enum):
    none = "NONE"
    source_hash_mismatch = "SOURCE_HASH_MISMATCH"
    non_positive_price = "NON_POSITIVE_PRICE"
    zero_anchor_price = "ZERO_ANCHOR_PRICE"
    zero_variance = "ZERO_VARIANCE"
    near_zero_variance = "NEAR_ZERO_VARIANCE"
    zero_range = "ZERO_RANGE"
    near_zero_volatility = "NEAR_ZERO_VOLATILITY"
    zero_atr = "ZERO_ATR"
    non_finite_input = "NON_FINITE_INPUT"
    non_finite_output = "NON_FINITE_OUTPUT"
    missing_volume = "MISSING_VOLUME"
    invalid_ohlc_input = "INVALID_OHLC_INPUT"
    invalid_ohlc_output = "INVALID_OHLC_OUTPUT"
    insufficient_bars = "INSUFFICIENT_BARS"
    interpolation_failure = "INTERPOLATION_FAILURE"
    precision_loss = "PRECISION_LOSS"
    unsupported_method = "UNSUPPORTED_METHOD"


@dataclass(frozen=True)
class NormalizationPolicies:
    source_hash_mismatch: str = "reject"
    non_positive_price: str = "reject"
    zero_variance: str = "reject"
    zero_range: str = "reject"
    zero_volatility: str = "reject"
    zero_atr: str = "reject"
    missing_volume: str = "allow"
    invalid_ohlc: str = "reject"
    ddof: int = 0
    minimum_std: float = 1e-12
    minimum_volatility: float = 1e-12
    minimum_atr: float = 1e-12
    range_centered: bool = False
    storage_decimals: int = 12
    calculation_dtype: str = "float64"


@dataclass
class NormalizationBuildResult:
    build: NormalizationBuild
    source_window_count: int = 0
    created_representations: int = 0
    existing_representations: int = 0
    skipped_representations: int = 0
    failed_representations: int = 0
    elapsed_seconds: float | None = None
    errors: list[str] = field(default_factory=list)


def normalization_configuration_hash(configuration: dict[str, Any]) -> str:
    return sha256_canonical(configuration)


def representation_hash(payload: dict[str, Any]) -> str:
    return sha256_canonical(payload)


def _values_from_bars(bars: list[PriceBar], channel: str) -> np.ndarray:
    values = np.asarray([float(getattr(bar, channel)) for bar in bars], dtype=np.float64)
    if not np.all(np.isfinite(values)):
        raise ValueError("NORMALIZATION_NON_FINITE_INPUT")
    return values


def _close(bars: list[PriceBar]) -> np.ndarray:
    return _values_from_bars(bars, "close")


def _ohlc_valid(bars: list[PriceBar]) -> bool:
    for bar in bars:
        open_, high, low, close = map(float, [bar.open, bar.high, bar.low, bar.close])
        if min(open_, high, low, close) <= 0:
            return False
        if high < max(open_, low, close) or low > min(open_, high, close):
            return False
    return True


def _round_values(values: dict[str, list[float]], decimals: int) -> dict[str, list[float]]:
    return {
        channel: [round(float(value), decimals) for value in series]
        for channel, series in values.items()
    }


def normalize_bars(
    bars: list[PriceBar],
    method: NormalizationMethodDefinition,
    policies: NormalizationPolicies,
) -> tuple[dict[str, list[float]], list[str], dict[str, Any]]:
    flags: set[str] = set()
    if len(bars) < method.minimum_bars:
        raise ValueError("NORMALIZATION_INSUFFICIENT_BARS")
    closes = _close(bars)
    if np.any(closes <= 0):
        flags.add(NormalizationQualityFlag.non_positive_price.value)
        if policies.non_positive_price == "reject":
            raise ValueError("NORMALIZATION_NON_POSITIVE_PRICE")
    if method.supports_ohlc and not _ohlc_valid(bars):
        flags.add(NormalizationQualityFlag.invalid_ohlc_input.value)
        if policies.invalid_ohlc == "reject":
            raise ValueError("NORMALIZATION_INVALID_OHLC_INPUT")
    anchor = float(closes[0])
    if anchor == 0:
        raise ValueError("NORMALIZATION_ZERO_ANCHOR")
    diagnostics: dict[str, Any] = {
        "source_bar_count": len(bars),
        "source_min": float(np.min(closes)),
        "source_max": float(np.max(closes)),
        "source_mean": float(np.mean(closes)),
        "source_std": float(np.std(closes, ddof=policies.ddof)),
        "source_range": float(np.max(closes) - np.min(closes)),
        "calculation_dtype": policies.calculation_dtype,
        "storage_precision": policies.storage_decimals,
    }
    output: dict[str, list[float]]
    code = method.code
    if code == "anchored_simple_return":
        output = {"close": list(closes / anchor - 1.0)}
    elif code == "anchored_log_return":
        if np.any(closes <= 0):
            raise ValueError("NORMALIZATION_NON_POSITIVE_PRICE")
        output = {"close": list(np.log(closes / anchor))}
    elif code == "anchored_ohlc":
        output = {channel: list(_values_from_bars(bars, channel) / anchor - 1.0) for channel in method.channels}
    elif code == "zscore_close":
        std = float(np.std(closes, ddof=policies.ddof))
        if std < policies.minimum_std:
            flags.add(NormalizationQualityFlag.zero_variance.value)
            if policies.zero_variance == "all_zero_with_flag":
                output = {"close": [0.0 for _ in closes]}
            else:
                raise ValueError("NORMALIZATION_ZERO_VARIANCE")
        else:
            output = {"close": list((closes - float(np.mean(closes))) / std)}
    elif code == "range_close":
        min_, max_ = float(np.min(closes)), float(np.max(closes))
        range_ = max_ - min_
        if range_ < policies.minimum_std:
            flags.add(NormalizationQualityFlag.zero_range.value)
            raise ValueError("NORMALIZATION_ZERO_RANGE")
        values = (closes - min_) / range_
        if policies.range_centered:
            values = 2.0 * values - 1.0
        output = {"close": list(values)}
    elif code == "volatility_targeted_return":
        returns = np.diff(np.log(closes))
        sigma = float(np.std(returns, ddof=policies.ddof))
        diagnostics["source_realized_volatility"] = sigma
        if sigma < policies.minimum_volatility:
            flags.add(NormalizationQualityFlag.near_zero_volatility.value)
            raise ValueError("NORMALIZATION_ZERO_VOLATILITY")
        output = {"close": [0.0, *list(np.cumsum(returns / sigma))]}
    elif code == "atr_anchored_ohlc":
        highs, lows = _values_from_bars(bars, "high"), _values_from_bars(bars, "low")
        true_ranges = [float(highs[0] - lows[0])]
        for idx in range(1, len(bars)):
            prev_close = closes[idx - 1]
            true_ranges.append(float(max(highs[idx] - lows[idx], abs(highs[idx] - prev_close), abs(lows[idx] - prev_close))))
        atr = float(np.mean(true_ranges))
        diagnostics["source_atr"] = atr
        if atr < policies.minimum_atr:
            flags.add(NormalizationQualityFlag.zero_atr.value)
            raise ValueError("NORMALIZATION_ZERO_ATR")
        output = {channel: list((_values_from_bars(bars, channel) - anchor) / atr) for channel in method.channels}
    elif code == "volume_relative_mean":
        volumes = _values_from_bars(bars, "volume")
        if np.any(np.isnan(volumes)):
            flags.add(NormalizationQualityFlag.missing_volume.value)
        mean_volume = float(np.mean(volumes))
        if math.isclose(mean_volume, 0.0):
            raise ValueError("NORMALIZATION_ZERO_RANGE")
        output = {"volume": list(volumes / mean_volume)}
    else:
        raise ValueError("NORMALIZATION_METHOD_NOT_FOUND")
    for series in output.values():
        if not np.all(np.isfinite(np.asarray(series, dtype=np.float64))):
            raise ValueError("NORMALIZATION_NON_FINITE_OUTPUT")
    diagnostics.update({
        "channel_count": len(output),
        "normalized_min": float(min(min(v) for v in output.values())),
        "normalized_max": float(max(max(v) for v in output.values())),
        "normalized_mean": float(np.mean([x for v in output.values() for x in v])),
        "normalized_std": float(np.std([x for v in output.values() for x in v])),
        "endpoint_value": float(next(iter(output.values()))[-1]),
        "contains_nan": False,
        "contains_infinity": False,
    })
    return {k: [float(x) for x in v] for k, v in output.items()}, sorted(flags) or [NormalizationQualityFlag.none.value], diagnostics


class NormalizationBuildService:
    def __init__(self, session: Session):
        self.session = session
        self._bar_cache: dict[tuple[str, str], tuple[list[datetime], list[PriceBar]]] = {}

    def build(
        self,
        normalization_method: str,
        resample_points: int,
        resampling_method: str = "linear",
        instrument_id: str | None = None,
        timeframe_id: str | None = None,
        window_length: int | None = None,
        start_timestamp: datetime | None = None,
        end_timestamp: datetime | None = None,
        mode: str = "incremental",
        normalization_version: str = "normalization_v1",
        source_window_version: str = "window_v1",
        policies: NormalizationPolicies | None = None,
    ) -> NormalizationBuildResult:
        started = time.monotonic()
        method = get_method(normalization_method)
        policies = policies or NormalizationPolicies()
        if mode not in {"full", "incremental", "range"} or resample_points < 2 or resampling_method not in {"linear", "previous"}:
            raise ValueError("NORMALIZATION_CONFIGURATION_INVALID")
        configuration = {
            "normalization_method": normalization_method,
            "normalization_version": normalization_version,
            "resampling_method": resampling_method,
            "resample_points": resample_points,
            "source_window_version": source_window_version,
            "instrument_id": instrument_id,
            "timeframe_id": timeframe_id,
            "window_length": window_length,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
            "policies": policies.__dict__,
        }
        config_hash = normalization_configuration_hash(configuration)
        build = NormalizationBuild(
            normalization_method=normalization_method,
            normalization_version=normalization_version,
            resampling_method=resampling_method,
            resample_points=resample_points,
            source_window_version=source_window_version,
            instrument_id=instrument_id,
            timeframe_id=timeframe_id,
            window_length=window_length,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            mode=mode,
            configuration=configuration,
            configuration_hash=config_hash,
            status=NormalizationBuildStatus.running.value,
            started_at=datetime.now(UTC),
        )
        self.session.add(build)
        self.session.flush()
        result = NormalizationBuildResult(build=build)
        try:
            windows = self._select_windows(instrument_id, timeframe_id, window_length, start_timestamp, end_timestamp, source_window_version)
            result.source_window_count = len(windows)
            existing_keys = self._existing_keys(normalization_method, normalization_version, resampling_method, resample_points, config_hash)
            for window in windows:
                key = (window.id, normalization_method, normalization_version, resampling_method, resample_points, config_hash, window.source_data_hash)
                if mode == "incremental" and key in existing_keys:
                    result.existing_representations += 1
                    continue
                try:
                    bars = self._window_bars(window)
                    recalculated = source_data_hash(bars)
                    if recalculated != window.source_data_hash and policies.source_hash_mismatch == "reject":
                        raise ValueError("NORMALIZATION_SOURCE_HASH_MISMATCH")
                    values, flags, diagnostics = normalize_bars(bars, method, policies)
                    resampled = _round_values(resample_channels(values, resample_points, resampling_method), policies.storage_decimals)
                    diagnostics["output_point_count"] = resample_points
                    diagnostics["source_window_hash_verified"] = recalculated == window.source_data_hash
                    schema = {"schema": method.channel_schema, "channels": method.channels, "points": resample_points}
                    rep_hash = representation_hash({
                        "channel_schema": schema,
                        "values": resampled,
                        "method": normalization_method,
                        "version": normalization_version,
                        "resampling_method": resampling_method,
                        "resample_points": resample_points,
                        "precision": policies.storage_decimals,
                        "source_window_hash": window.source_data_hash,
                        "configuration_hash": config_hash,
                    })
                    if key in existing_keys:
                        result.existing_representations += 1
                        continue
                    self.session.add(NormalizedPattern(
                        pattern_window_id=window.id,
                        normalization_method=normalization_method,
                        normalization_version=normalization_version,
                        resampling_method=resampling_method,
                        resample_points=resample_points,
                        source_window_hash=window.source_data_hash,
                        configuration_hash=config_hash,
                        representation_hash=rep_hash,
                        channel_schema=schema,
                        normalized_values=resampled,
                        diagnostics=diagnostics,
                        quality_flags=flags,
                    ))
                    existing_keys.add(key)
                    result.created_representations += 1
                except ValueError as exc:
                    result.failed_representations += 1
                    result.errors.append(str(exc))
            result.elapsed_seconds = round(time.monotonic() - started, 3)
            build.source_window_count = result.source_window_count
            build.created_representation_count = result.created_representations
            build.existing_representation_count = result.existing_representations
            build.skipped_representation_count = result.skipped_representations
            build.failed_representation_count = result.failed_representations
            build.status = NormalizationBuildStatus.completed_with_warnings.value if result.failed_representations else NormalizationBuildStatus.completed.value
            build.error_message = "; ".join(result.errors[:5]) or None
            build.completed_at = datetime.now(UTC)
            build.elapsed_seconds = result.elapsed_seconds
            self.session.commit()
            self.session.refresh(build)
            return result
        except Exception as exc:
            build.status = NormalizationBuildStatus.failed.value
            build.error_message = str(exc)
            build.completed_at = datetime.now(UTC)
            build.elapsed_seconds = round(time.monotonic() - started, 3)
            self.session.commit()
            raise

    def _select_windows(self, instrument_id, timeframe_id, window_length, start_timestamp, end_timestamp, source_window_version):
        query = select(PatternWindow).where(PatternWindow.window_version == source_window_version)
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
        return list(self.session.scalars(query.order_by(PatternWindow.end_timestamp, PatternWindow.id)))

    def _window_bars(self, window: PatternWindow) -> list[PriceBar]:
        key = (window.instrument_id, window.timeframe_id)
        if key not in self._bar_cache:
            bars = list(
                self.session.scalars(
                    select(PriceBar)
                    .where(
                        PriceBar.instrument_id == window.instrument_id,
                        PriceBar.timeframe_id == window.timeframe_id,
                    )
                    .order_by(PriceBar.timestamp, PriceBar.id)
                )
            )
            self._bar_cache[key] = ([bar.timestamp for bar in bars], bars)
        timestamps, bars = self._bar_cache[key]
        left = bisect_left(timestamps, window.start_timestamp)
        right = bisect_right(timestamps, window.end_timestamp)
        return bars[left:right]

    def _existing_keys(self, method, version, resampling, points, config_hash):
        rows = self.session.execute(
            select(
                NormalizedPattern.pattern_window_id,
                NormalizedPattern.normalization_method,
                NormalizedPattern.normalization_version,
                NormalizedPattern.resampling_method,
                NormalizedPattern.resample_points,
                NormalizedPattern.configuration_hash,
                NormalizedPattern.source_window_hash,
            ).where(
                NormalizedPattern.normalization_method == method,
                NormalizedPattern.normalization_version == version,
                NormalizedPattern.resampling_method == resampling,
                NormalizedPattern.resample_points == points,
                NormalizedPattern.configuration_hash == config_hash,
            )
        )
        return {tuple(row) for row in rows}
