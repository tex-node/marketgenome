from __future__ import annotations

import math
import time
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import numpy as np
from market_genome_domain.models import (
    OutcomeBuild,
    OutcomeBuildStatus,
    OutcomeObservation,
    PatternWindow,
    PriceBar,
)
from market_genome_shared.hashing import sha256_canonical
from market_genome_window_engine.service import source_data_hash
from sqlalchemy import select
from sqlalchemy.orm import Session

from market_genome_outcomes.definitions import OutcomeSetDefinition, get_outcome_set


@dataclass
class ComputedOutcome:
    scalar_values: dict[str, Any]
    forward_path: dict[str, Any]
    barrier_results: dict[str, Any]
    diagnostics: dict[str, Any]
    quality_flags: list[str]
    future_bar_hash: str
    path_hash: str
    outcome_hash: str


@dataclass
class OutcomeBuildResult:
    build: OutcomeBuild
    source_pattern_count: int = 0
    eligible_pattern_count: int = 0
    created_observations: int = 0
    existing_observations: int = 0
    partial_observations: int = 0
    skipped_patterns: int = 0
    failed_observations: int = 0
    elapsed_seconds: float | None = None
    errors: list[str] = field(default_factory=list)


def outcome_configuration_hash(configuration: dict[str, Any]) -> str:
    return sha256_canonical(configuration)


def future_bar_hash(bars: list[PriceBar]) -> str:
    return sha256_canonical(
        [
            {
                "instrument_id": bar.instrument_id,
                "timeframe_id": bar.timeframe_id,
                "timestamp": bar.timestamp,
                "open": _numeric(bar.open),
                "high": _numeric(bar.high),
                "low": _numeric(bar.low),
                "close": _numeric(bar.close),
                "volume": None if bar.volume is None else _numeric(bar.volume),
            }
            for bar in bars
        ]
    )


def path_hash(path: dict[str, Any]) -> str:
    return sha256_canonical(path)


def outcome_hash(payload: dict[str, Any]) -> str:
    return sha256_canonical(payload)


def _numeric(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return format(float(value), ".12g")


def _round(value: float | None, decimals: int) -> float | None:
    if value is None:
        return None
    return round(float(value), decimals)


def _direction(value: float | None, cfg: dict[str, Any]) -> str:
    if value is None:
        return "UNAVAILABLE"
    tol = cfg["flat_tolerance"]
    if value > max(cfg["positive_threshold"], tol):
        return "POSITIVE"
    if value < min(cfg["negative_threshold"], -tol):
        return "NEGATIVE"
    return "FLAT"


def _continuation_reversal(source_return: float | None, future_return: float | None, cfg: dict[str, Any]) -> str:
    if future_return is None:
        return "UNAVAILABLE"
    if source_return is None or abs(source_return) < cfg["minimum_source_displacement"]:
        return "SOURCE_DIRECTION_UNAVAILABLE"
    if abs(future_return) <= max(abs(cfg["continuation_threshold"]), abs(cfg["reversal_threshold"]), 1e-12):
        return "SIDEWAYS"
    if source_return > 0 and future_return > 0:
        return "CONTINUATION"
    if source_return > 0 and future_return < 0:
        return "REVERSAL"
    if source_return < 0 and future_return < 0:
        return "CONTINUATION"
    if source_return < 0 and future_return > 0:
        return "REVERSAL"
    return "SIDEWAYS"


def _barrier_state(bars: list[PriceBar], anchor: float, upside: float, downside: float) -> dict[str, Any]:
    up_price = anchor * (1.0 + upside)
    down_price = anchor * (1.0 + downside)
    for idx, bar in enumerate(bars, start=1):
        hit_up = float(bar.high) >= up_price
        hit_down = float(bar.low) <= down_price
        if hit_up and hit_down:
            return {"state": "SAME_BAR_BOTH", "bar": idx, "timestamp": bar.timestamp.isoformat(), "upside": upside, "downside": downside}
        if hit_up:
            return {"state": "UP_FIRST", "bar": idx, "timestamp": bar.timestamp.isoformat(), "upside": upside, "downside": downside}
        if hit_down:
            return {"state": "DOWN_FIRST", "bar": idx, "timestamp": bar.timestamp.isoformat(), "upside": upside, "downside": downside}
    return {"state": "NEITHER", "bar": None, "timestamp": None, "upside": upside, "downside": downside}


def _first_threshold_sequence(bars: list[PriceBar], anchor: float, gain: float, drawdown: float) -> tuple[str, str]:
    gain_price = anchor * (1.0 + gain)
    drawdown_price = anchor * (1.0 + drawdown)
    for bar in bars:
        hit_gain = float(bar.high) >= gain_price
        hit_drawdown = float(bar.low) <= drawdown_price
        if hit_gain and hit_drawdown:
            return "SAME_BAR_BOTH", "SAME_BAR_BOTH"
        if hit_gain:
            return "GAIN_FIRST", "DRAWDOWN_AFTER_GAIN_UNKNOWN"
        if hit_drawdown:
            return "GAIN_AFTER_DRAWDOWN_UNKNOWN", "DRAWDOWN_FIRST"
    return "NEITHER", "NEITHER"


def _drawdown_runup(closes: np.ndarray) -> tuple[float | None, float | None, dict[str, Any]]:
    if len(closes) == 0:
        return None, None, {}
    peaks = np.maximum.accumulate(closes)
    drawdowns = closes / peaks - 1.0
    dd_end = int(np.argmin(drawdowns))
    dd_start = int(np.argmax(closes[: dd_end + 1]))
    troughs = np.minimum.accumulate(closes)
    runups = closes / troughs - 1.0
    ru_end = int(np.argmax(runups))
    ru_start = int(np.argmin(closes[: ru_end + 1]))
    return (
        float(np.min(drawdowns)),
        float(np.max(runups)),
        {
            "drawdown_start_bar": dd_start + 1,
            "drawdown_end_bar": dd_end + 1,
            "drawdown_duration_bars": max(0, dd_end - dd_start),
            "runup_start_bar": ru_start + 1,
            "runup_end_bar": ru_end + 1,
            "runup_duration_bars": max(0, ru_end - ru_start),
        },
    )


def compute_outcome(
    window: PatternWindow,
    anchor_bar: PriceBar,
    future_bars: list[PriceBar],
    horizon: int,
    outcome_set: OutcomeSetDefinition | None = None,
    configuration_hash: str | None = None,
    source_return: float | None = None,
) -> ComputedOutcome:
    outcome_set = outcome_set or get_outcome_set("forward_outcomes_v1")
    cfg = outcome_set.configuration
    decimals = cfg["precision"]["storage_decimals"]
    flags: list[str] = []
    if horizon <= 0:
        raise ValueError("OUTCOME_HORIZON_INVALID")
    anchor = float(anchor_bar.close)
    if anchor <= 0 or not math.isfinite(anchor):
        raise ValueError("OUTCOME_NON_POSITIVE_PRICE")
    selected = future_bars[:horizon]
    if any(bar.timestamp <= window.end_timestamp for bar in selected):
        raise ValueError("OUTCOME_ANCHOR_BAR_MISMATCH")
    timestamps = [bar.timestamp for bar in selected]
    if len(timestamps) != len(set(timestamps)):
        raise ValueError("OUTCOME_DUPLICATE_FUTURE_TIMESTAMP")
    if timestamps != sorted(timestamps):
        raise ValueError("OUTCOME_FUTURE_DATA_INVALID")
    available = len(selected)
    complete = available >= horizon
    if not complete:
        flags.append("PARTIAL_HORIZON")
    if available == 0:
        flags.append("NO_FUTURE_BARS")
        fh = future_bar_hash([])
        forward_path = {
            "schema": cfg["forward_path"]["path_schema"],
            "normalization_method": cfg["forward_path"]["normalization_method"],
            "include_anchor": True,
            "point_count": 1,
            "values": [0.0],
            "path_hash": "",
        }
        ph = path_hash(forward_path | {"path_hash": ""})
        forward_path["path_hash"] = ph
        scalar = _empty_scalar()
        oh = outcome_hash({"window": window.id, "horizon": horizon, "scalar": scalar, "future_bar_hash": fh, "path_hash": ph, "configuration_hash": configuration_hash})
        return ComputedOutcome(
            scalar,
            forward_path,
            {},
            {"available_future_bars": 0, "is_complete": False, "anchor_excluded_from_future": True},
            flags,
            fh,
            ph,
            oh,
        )
    closes = np.asarray([float(bar.close) for bar in selected], dtype=np.float64)
    highs = np.asarray([float(bar.high) for bar in selected], dtype=np.float64)
    lows = np.asarray([float(bar.low) for bar in selected], dtype=np.float64)
    if np.any(closes <= 0) or not np.all(np.isfinite(closes)):
        raise ValueError("OUTCOME_NON_POSITIVE_PRICE")
    final_close = float(closes[-1])
    simple = final_close / anchor - 1.0
    log_return = math.log(final_close / anchor)
    high_returns = highs / anchor - 1.0
    low_returns = lows / anchor - 1.0
    mfe_idx = int(np.argmax(high_returns))
    mae_idx = int(np.argmin(low_returns))
    mfe = float(high_returns[mfe_idx])
    mae = float(low_returns[mae_idx])
    path_values = [0.0, *[float(math.log(close / anchor)) for close in closes]]
    path_diffs = np.abs(np.diff(np.asarray(path_values, dtype=np.float64)))
    path_length = float(np.sum(path_diffs))
    path_eff = None if path_length <= 1e-12 else abs(path_values[-1] - path_values[0]) / path_length
    returns = np.diff(np.asarray([anchor, *closes], dtype=np.float64))
    log_steps = np.diff(np.log(np.asarray([anchor, *closes], dtype=np.float64)))
    ddof = cfg["volatility"]["standard_deviation_ddof"]
    realized_vol = None if len(log_steps) <= ddof else float(np.std(log_steps, ddof=ddof))
    max_dd, max_ru, dd_diag = _drawdown_runup(closes)
    direction = _direction(simple, cfg["classifications"]["direction"])
    cont_rev = _continuation_reversal(source_return, simple, cfg["classifications"]["continuation_reversal"])
    barriers = {
        f"{up:+.4f}/{down:+.4f}": _barrier_state(selected, anchor, up, down)
        for up in cfg["barriers"]["upside"]
        for down in cfg["barriers"]["downside"]
        if abs(up) == abs(down)
    }
    first_barrier = next((item["state"] for item in barriers.values() if item["state"] != "NEITHER"), "NEITHER")
    gain_first, drawdown_first = _first_threshold_sequence(
        selected,
        anchor,
        cfg["sequencing"]["gain_threshold"],
        cfg["sequencing"]["drawdown_threshold"],
    )
    scalar = {
        "future_simple_return": _round(simple, decimals),
        "future_log_return": _round(log_return, decimals),
        "maximum_favourable_excursion": _round(mfe, decimals),
        "maximum_adverse_excursion": _round(mae, decimals),
        "time_to_mfe_bars": mfe_idx + 1,
        "time_to_mae_bars": mae_idx + 1,
        "future_realized_volatility": _round(realized_vol, decimals),
        "future_path_efficiency": _round(path_eff, decimals),
        "future_maximum_drawdown": _round(max_dd, decimals),
        "future_maximum_runup": _round(max_ru, decimals),
        "direction_class": direction,
        "continuation_reversal_class": cont_rev,
        "first_barrier_hit": first_barrier,
        "gain_before_drawdown": gain_first,
        "drawdown_before_gain": drawdown_first,
    }
    forward_path = {
        "schema": cfg["forward_path"]["path_schema"],
        "normalization_method": cfg["forward_path"]["normalization_method"],
        "include_anchor": True,
        "point_count": len(path_values),
        "source_future_bar_count": available,
        "values": [_round(value, decimals) for value in path_values],
        "path_hash": "",
    }
    ph = path_hash(forward_path | {"path_hash": ""})
    forward_path["path_hash"] = ph
    fh = future_bar_hash(selected)
    diagnostics = {
        "anchor_excluded_from_future": True,
        "horizon_bars": horizon,
        "available_future_bars": available,
        "is_complete": complete,
        "first_future_timestamp": selected[0].timestamp.isoformat(),
        "last_future_timestamp": selected[-1].timestamp.isoformat(),
        "path_length": path_length,
        "drawdown_runup": dd_diag,
        "future_return_sum_basis": float(np.sum(returns)),
        "source_direction_basis": "pattern_window_close_endpoint",
        "source_endpoint_return": None if source_return is None else _round(source_return, decimals),
    }
    oh = outcome_hash(
        {
            "pattern_window_id": window.id,
            "horizon": horizon,
            "is_complete": complete,
            "scalar": scalar,
            "forward_path": forward_path,
            "barriers": barriers,
            "future_bar_hash": fh,
            "path_hash": ph,
            "configuration_hash": configuration_hash,
        }
    )
    return ComputedOutcome(scalar, forward_path, barriers, diagnostics, flags or ["NONE"], fh, ph, oh)


def _empty_scalar() -> dict[str, Any]:
    return {
        "future_simple_return": None,
        "future_log_return": None,
        "maximum_favourable_excursion": None,
        "maximum_adverse_excursion": None,
        "time_to_mfe_bars": None,
        "time_to_mae_bars": None,
        "future_realized_volatility": None,
        "future_path_efficiency": None,
        "future_maximum_drawdown": None,
        "future_maximum_runup": None,
        "direction_class": "UNAVAILABLE",
        "continuation_reversal_class": "UNAVAILABLE",
        "first_barrier_hit": "UNAVAILABLE",
        "gain_before_drawdown": "UNAVAILABLE",
        "drawdown_before_gain": "UNAVAILABLE",
    }


def _source_endpoint_return(window_bars: list[PriceBar]) -> float | None:
    if len(window_bars) < 2:
        return None
    first = float(window_bars[0].close)
    last = float(window_bars[-1].close)
    if first <= 0 or not math.isfinite(first) or not math.isfinite(last):
        return None
    return last / first - 1.0


class OutcomeBuildService:
    def __init__(self, session: Session):
        self.session = session
        self._bar_cache: dict[tuple[str, str], tuple[list[datetime], list[PriceBar]]] = {}

    def build(
        self,
        outcome_set_code: str = "forward_outcomes_v1",
        horizons: list[int] | None = None,
        mode: str = "incremental",
        instrument_id: str | None = None,
        timeframe_id: str | None = None,
        window_length: int | None = None,
        start_timestamp: datetime | None = None,
        end_timestamp: datetime | None = None,
    ) -> OutcomeBuildResult:
        started = time.monotonic()
        if mode not in {"full", "incremental", "range"}:
            raise ValueError("OUTCOME_CONFIGURATION_INVALID")
        outcome_set = get_outcome_set(outcome_set_code)
        requested_horizons = sorted(set(horizons or outcome_set.default_horizons))
        if not requested_horizons or any(h <= 0 for h in requested_horizons):
            raise ValueError("OUTCOME_HORIZON_INVALID")
        configuration = {
            "outcome_set_code": outcome_set.code,
            "outcome_set_version": outcome_set.version,
            "outcome_set_configuration": outcome_set.configuration,
            "requested_horizons": requested_horizons,
            "instrument_id": instrument_id,
            "timeframe_id": timeframe_id,
            "window_length": window_length,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
        }
        config_hash = outcome_configuration_hash(configuration)
        build = OutcomeBuild(
            outcome_set_code=outcome_set.code,
            outcome_set_version=outcome_set.version,
            instrument_id=instrument_id,
            timeframe_id=timeframe_id,
            window_length=window_length,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            requested_horizons=requested_horizons,
            mode=mode,
            configuration=configuration,
            configuration_hash=config_hash,
            status=OutcomeBuildStatus.running.value,
            started_at=datetime.now(UTC),
        )
        self.session.add(build)
        self.session.flush()
        result = OutcomeBuildResult(build=build)
        try:
            windows = self._select_windows(instrument_id, timeframe_id, window_length, start_timestamp, end_timestamp)
            result.source_pattern_count = len(windows)
            window_ids = {window.id for window in windows}
            existing = self._existing_keys(outcome_set, config_hash, window_ids)
            latest_partials = self._latest_partials(outcome_set, config_hash, window_ids)
            for window in windows:
                bars = self._bars(window.instrument_id, window.timeframe_id)
                timestamps = self._timestamps(window.instrument_id, window.timeframe_id)
                anchor_index = self._anchor_index(window, timestamps, bars)
                if anchor_index is None:
                    result.skipped_patterns += 1
                    continue
                anchor_bar = bars[anchor_index]
                window_bars = bars[anchor_index - window.window_length + 1 : anchor_index + 1]
                if len(window_bars) != window.window_length or source_data_hash(window_bars) != window.source_data_hash:
                    result.failed_observations += len(requested_horizons)
                    result.errors.append("OUTCOME_SOURCE_WINDOW_HASH_MISMATCH")
                    continue
                result.eligible_pattern_count += 1
                future = bars[anchor_index + 1 : anchor_index + 1 + max(requested_horizons)]
                for horizon in requested_horizons:
                    try:
                        computed = compute_outcome(
                            window,
                            anchor_bar,
                            future,
                            horizon,
                            outcome_set,
                            config_hash,
                            source_return=_source_endpoint_return(window_bars),
                        )
                        key = (
                            window.id,
                            outcome_set.code,
                            outcome_set.version,
                            horizon,
                            window.source_data_hash,
                            computed.future_bar_hash,
                            config_hash,
                            computed.diagnostics["is_complete"],
                        )
                        if mode == "incremental" and key in existing:
                            result.existing_observations += 1
                            continue
                        if key in existing:
                            result.existing_observations += 1
                            continue
                        previous_partial = (
                            latest_partials.get((window.id, horizon))
                            if computed.diagnostics["is_complete"]
                            else None
                        )
                        observation = OutcomeObservation(
                            pattern_window_id=window.id,
                            instrument_id=window.instrument_id,
                            timeframe_id=window.timeframe_id,
                            window_length=window.window_length,
                            window_start_timestamp=window.start_timestamp,
                            window_end_timestamp=window.end_timestamp,
                            outcome_set_code=outcome_set.code,
                            outcome_set_version=outcome_set.version,
                            horizon_bars=horizon,
                            available_future_bars=computed.diagnostics["available_future_bars"],
                            is_complete=computed.diagnostics["is_complete"],
                            anchor_timestamp=window.end_timestamp,
                            anchor_price=float(anchor_bar.close),
                            first_future_timestamp=datetime.fromisoformat(computed.diagnostics["first_future_timestamp"]) if "first_future_timestamp" in computed.diagnostics else None,
                            last_future_timestamp=datetime.fromisoformat(computed.diagnostics["last_future_timestamp"]) if "last_future_timestamp" in computed.diagnostics else None,
                            future_simple_return=computed.scalar_values["future_simple_return"],
                            future_log_return=computed.scalar_values["future_log_return"],
                            maximum_favourable_excursion=computed.scalar_values["maximum_favourable_excursion"],
                            maximum_adverse_excursion=computed.scalar_values["maximum_adverse_excursion"],
                            time_to_mfe_bars=computed.scalar_values["time_to_mfe_bars"],
                            time_to_mae_bars=computed.scalar_values["time_to_mae_bars"],
                            future_realized_volatility=computed.scalar_values["future_realized_volatility"],
                            future_path_efficiency=computed.scalar_values["future_path_efficiency"],
                            future_maximum_drawdown=computed.scalar_values["future_maximum_drawdown"],
                            future_maximum_runup=computed.scalar_values["future_maximum_runup"],
                            direction_class=computed.scalar_values["direction_class"],
                            continuation_reversal_class=computed.scalar_values["continuation_reversal_class"],
                            first_barrier_hit=computed.scalar_values["first_barrier_hit"],
                            gain_before_drawdown=computed.scalar_values["gain_before_drawdown"],
                            drawdown_before_gain=computed.scalar_values["drawdown_before_gain"],
                            source_window_hash=window.source_data_hash,
                            future_bar_hash=computed.future_bar_hash,
                            configuration_hash=config_hash,
                            outcome_hash=computed.outcome_hash,
                            scalar_values=computed.scalar_values,
                            forward_path=computed.forward_path,
                            barrier_results=computed.barrier_results,
                            diagnostics=computed.diagnostics,
                            quality_flags=computed.quality_flags,
                            supersedes_observation_id=previous_partial.id if previous_partial and computed.diagnostics["is_complete"] else None,
                        )
                        self.session.add(observation)
                        existing.add(key)
                        result.created_observations += 1
                        if not computed.diagnostics["is_complete"]:
                            result.partial_observations += 1
                    except ValueError as exc:
                        result.failed_observations += 1
                        result.errors.append(str(exc))
            result.elapsed_seconds = round(time.monotonic() - started, 3)
            build.source_pattern_count = result.source_pattern_count
            build.eligible_pattern_count = result.eligible_pattern_count
            build.created_observation_count = result.created_observations
            build.existing_observation_count = result.existing_observations
            build.partial_observation_count = result.partial_observations
            build.skipped_pattern_count = result.skipped_patterns
            build.failed_observation_count = result.failed_observations
            build.status = OutcomeBuildStatus.completed_with_warnings.value if result.partial_observations or result.failed_observations else OutcomeBuildStatus.completed.value
            build.error_message = "; ".join(result.errors[:5]) or None
            build.completed_at = datetime.now(UTC)
            build.elapsed_seconds = result.elapsed_seconds
            self.session.commit()
            self.session.refresh(build)
            return result
        except Exception as exc:
            build.status = OutcomeBuildStatus.failed.value
            build.error_message = str(exc)
            build.completed_at = datetime.now(UTC)
            build.elapsed_seconds = round(time.monotonic() - started, 3)
            self.session.commit()
            raise

    def _select_windows(self, instrument_id, timeframe_id, window_length, start_timestamp, end_timestamp):
        query = select(PatternWindow)
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

    def _bars(self, instrument_id: str, timeframe_id: str) -> list[PriceBar]:
        key = (instrument_id, timeframe_id)
        if key not in self._bar_cache:
            bars = list(
                self.session.scalars(
                    select(PriceBar)
                    .where(PriceBar.instrument_id == instrument_id, PriceBar.timeframe_id == timeframe_id)
                    .order_by(PriceBar.timestamp, PriceBar.id)
                )
            )
            self._bar_cache[key] = ([bar.timestamp for bar in bars], bars)
        return self._bar_cache[key][1]

    def _timestamps(self, instrument_id: str, timeframe_id: str) -> list[datetime]:
        self._bars(instrument_id, timeframe_id)
        return self._bar_cache[(instrument_id, timeframe_id)][0]

    def _anchor_index(self, window: PatternWindow, timestamps: list[datetime], bars: list[PriceBar]) -> int | None:
        idx = bisect_right(timestamps, window.end_timestamp) - 1
        if idx < 0 or bars[idx].timestamp != window.end_timestamp:
            return None
        return idx

    def _existing_keys(self, outcome_set, configuration_hash: str, window_ids: set[str]) -> set[tuple[Any, ...]]:
        if not window_ids:
            return set()
        rows = self.session.execute(
            select(
                OutcomeObservation.pattern_window_id,
                OutcomeObservation.outcome_set_code,
                OutcomeObservation.outcome_set_version,
                OutcomeObservation.horizon_bars,
                OutcomeObservation.source_window_hash,
                OutcomeObservation.future_bar_hash,
                OutcomeObservation.configuration_hash,
                OutcomeObservation.is_complete,
            ).where(
                OutcomeObservation.outcome_set_code == outcome_set.code,
                OutcomeObservation.outcome_set_version == outcome_set.version,
                OutcomeObservation.configuration_hash == configuration_hash,
                OutcomeObservation.pattern_window_id.in_(window_ids),
            )
        )
        return {tuple(row) for row in rows}

    def _latest_partial(self, window_id: str, outcome_set, horizon: int, configuration_hash: str) -> OutcomeObservation | None:
        return self.session.scalar(
            select(OutcomeObservation)
            .where(
                OutcomeObservation.pattern_window_id == window_id,
                OutcomeObservation.outcome_set_code == outcome_set.code,
                OutcomeObservation.outcome_set_version == outcome_set.version,
                OutcomeObservation.horizon_bars == horizon,
                OutcomeObservation.configuration_hash == configuration_hash,
                OutcomeObservation.is_complete.is_(False),
            )
            .order_by(OutcomeObservation.created_at.desc())
            .limit(1)
        )

    def _latest_partials(self, outcome_set, configuration_hash: str, window_ids: set[str]) -> dict[tuple[str, int], OutcomeObservation]:
        if not window_ids:
            return {}
        rows = self.session.scalars(
            select(OutcomeObservation)
            .where(
                OutcomeObservation.outcome_set_code == outcome_set.code,
                OutcomeObservation.outcome_set_version == outcome_set.version,
                OutcomeObservation.configuration_hash == configuration_hash,
                OutcomeObservation.is_complete.is_(False),
                OutcomeObservation.pattern_window_id.in_(window_ids),
            )
            .order_by(
                OutcomeObservation.pattern_window_id,
                OutcomeObservation.horizon_bars,
                OutcomeObservation.created_at.desc(),
            )
        )
        latest: dict[tuple[str, int], OutcomeObservation] = {}
        for row in rows:
            latest.setdefault((row.pattern_window_id, row.horizon_bars), row)
        return latest
