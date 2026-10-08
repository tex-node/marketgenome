from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from itertools import pairwise
from typing import Any

from market_genome_domain.models import PatternWindow, PriceBar, WindowBuild, WindowBuildStatus
from market_genome_shared.hashing import sha256_canonical
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

DEFAULT_WINDOW_LENGTHS = [8, 16, 32, 64, 128, 256]
CONTINUITY_POLICY_VERSIONS = {
    "continuous": "strict_elapsed_time_v1",
    "session_based": "observed_session_sequence_v1",
    "unknown": "unknown_calendar_policy_v1",
}


class WindowQualityFlag(str, Enum):
    none = "NONE"
    missing_bars = "MISSING_BARS"
    duplicate_timestamps = "DUPLICATE_TIMESTAMPS"
    non_monotonic_timestamps = "NON_MONOTONIC_TIMESTAMPS"
    null_volume = "NULL_VOLUME"
    zero_volume = "ZERO_VOLUME"
    extreme_gap = "EXTREME_GAP"
    invalid_ohlc = "INVALID_OHLC"
    source_data_changed = "SOURCE_DATA_CHANGED"
    insufficient_bars = "INSUFFICIENT_BARS"
    unknown_calendar = "UNKNOWN_CALENDAR"


@dataclass(frozen=True)
class WindowQualityPolicy:
    mode: str = "strict"
    maximum_missing_bars: int = 0
    maximum_gap_ratio: float = 0.0
    calendar_mode: str = "continuous"


@dataclass
class WindowBuildResult:
    build: WindowBuild
    candidate_windows: int = 0
    created_windows: int = 0
    existing_windows: int = 0
    skipped_windows: int = 0
    incomplete_windows: int = 0
    quality_warning_windows: int = 0
    bars_read: int = 0
    first_window_start: datetime | None = None
    last_window_end: datetime | None = None
    elapsed_seconds: float | None = None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _numeric(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return format(float(value), ".12g")


def source_data_hash(bars: list[PriceBar]) -> str:
    payload = [
        {
            "instrument_id": bar.instrument_id,
            "timeframe_id": bar.timeframe_id,
            "timestamp": _as_utc(bar.timestamp),
            "open": _numeric(bar.open),
            "high": _numeric(bar.high),
            "low": _numeric(bar.low),
            "close": _numeric(bar.close),
            "volume": None if bar.volume is None else _numeric(bar.volume),
        }
        for bar in bars
    ]
    return sha256_canonical(payload)


def build_configuration_hash(configuration: dict[str, Any]) -> str:
    return sha256_canonical(configuration)


def continuity_policy_version(policy: WindowQualityPolicy) -> str:
    return CONTINUITY_POLICY_VERSIONS[policy.calendar_mode]


def expected_window_count(bar_count: int, window_length: int, stride: int) -> int:
    if bar_count < window_length:
        return 0
    return ((bar_count - window_length) // stride) + 1


class WindowBuildService:
    def __init__(self, session: Session):
        self.session = session

    def build(
        self,
        instrument_id: str,
        timeframe_id: str,
        window_lengths: list[int] | None = None,
        stride: int = 1,
        start_timestamp: datetime | None = None,
        end_timestamp: datetime | None = None,
        quality_policy: WindowQualityPolicy | None = None,
        window_version: str = "window_v1",
        mode: str = "incremental",
    ) -> WindowBuildResult:
        started = time.monotonic()
        started_at = datetime.now(UTC)
        lengths = sorted(set(window_lengths or DEFAULT_WINDOW_LENGTHS))
        policy = quality_policy or WindowQualityPolicy()
        self._validate_configuration(lengths, stride, policy, mode)
        start_timestamp = _as_utc(start_timestamp)
        end_timestamp = _as_utc(end_timestamp)
        configuration = {
            "instrument_id": instrument_id,
            "timeframe_id": timeframe_id,
            "window_lengths": lengths,
            "stride": stride,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
            "quality_policy": policy.__dict__,
            "continuity_policy_version": continuity_policy_version(policy),
            "window_version": window_version,
            "mode": mode,
            "minimum_required_bars": max(lengths),
        }
        config_hash = build_configuration_hash(configuration)
        build = WindowBuild(
            instrument_id=instrument_id,
            timeframe_id=timeframe_id,
            requested_lengths=lengths,
            stride=stride,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            window_version=window_version,
            mode=mode,
            configuration=configuration,
            configuration_hash=config_hash,
            status=WindowBuildStatus.running.value,
            started_at=started_at,
        )
        self.session.add(build)
        self.session.flush()
        result = WindowBuildResult(build=build)
        try:
            bars = self._load_bars(instrument_id, timeframe_id, start_timestamp, end_timestamp)
            result.bars_read = len(bars)
            timestamps = [bar.timestamp for bar in bars]
            if len(set(timestamps)) != len(timestamps):
                raise ValueError("DUPLICATE_TIMESTAMPS")
            if timestamps != sorted(timestamps):
                raise ValueError("NON_MONOTONIC_TIMESTAMPS")

            max_length = max(lengths)
            if len(bars) < min(lengths):
                result.incomplete_windows = len(lengths)

            existing_keys = self._existing_window_keys(
                instrument_id,
                timeframe_id,
                lengths,
                window_version,
                config_hash,
            )
            for length in lengths:
                effective_start_index = length - 1
                if mode == "incremental":
                    latest = self._latest_end_timestamp(
                        instrument_id,
                        timeframe_id,
                        length,
                        window_version,
                        config_hash,
                    )
                    if latest is not None:
                        for index, bar in enumerate(bars):
                            if bar.timestamp > latest:
                                effective_start_index = max(length - 1, index)
                                break
                        else:
                            continue
                for end_index in range(effective_start_index, len(bars), stride):
                    candidate = bars[end_index - length + 1 : end_index + 1]
                    if len(candidate) != length:
                        result.incomplete_windows += 1
                        continue
                    result.candidate_windows += 1
                    flags = self._quality_flags(candidate, policy)
                    if self._reject_for_quality(flags, policy):
                        result.skipped_windows += 1
                        if WindowQualityFlag.missing_bars.value in flags:
                            result.incomplete_windows += 1
                        continue
                    if flags and flags != [WindowQualityFlag.none.value]:
                        result.quality_warning_windows += 1
                    digest = source_data_hash(candidate)
                    key = (candidate[-1].timestamp, length, window_version, digest, config_hash)
                    if key in existing_keys:
                        result.existing_windows += 1
                        continue
                    window = PatternWindow(
                        instrument_id=instrument_id,
                        timeframe_id=timeframe_id,
                        start_timestamp=candidate[0].timestamp,
                        end_timestamp=candidate[-1].timestamp,
                        start_bar_id=candidate[0].id,
                        end_bar_id=candidate[-1].id,
                        window_length=length,
                        stride=stride,
                        bar_count=len(candidate),
                        window_version=window_version,
                        source_data_hash=digest,
                        build_configuration_hash=config_hash,
                        is_complete=not flags or flags == [WindowQualityFlag.none.value],
                        quality_flags=flags or [WindowQualityFlag.none.value],
                    )
                    self.session.add(window)
                    existing_keys.add(key)
                    result.created_windows += 1
                    result.first_window_start = result.first_window_start or candidate[0].timestamp
                    result.last_window_end = candidate[-1].timestamp
                if len(bars) < max_length:
                    result.incomplete_windows += 1

            completed_at = datetime.now(UTC)
            result.elapsed_seconds = round(time.monotonic() - started, 3)
            build.status = (
                WindowBuildStatus.completed_with_warnings.value
                if result.quality_warning_windows or result.incomplete_windows
                else WindowBuildStatus.completed.value
            )
            build.completed_at = completed_at
            self._copy_result_to_build(build, result)
            self.session.commit()
            self.session.refresh(build)
            return result
        except Exception as exc:
            build.status = WindowBuildStatus.failed.value
            build.error_message = str(exc)
            build.completed_at = datetime.now(UTC)
            build.elapsed_seconds = round(time.monotonic() - started, 3)
            self.session.commit()
            raise

    def _copy_result_to_build(self, build: WindowBuild, result: WindowBuildResult) -> None:
        build.source_bar_count = result.bars_read
        build.candidate_windows = result.candidate_windows
        build.created_window_count = result.created_windows
        build.existing_window_count = result.existing_windows
        build.skipped_window_count = result.skipped_windows
        build.incomplete_window_count = result.incomplete_windows
        build.quality_warning_window_count = result.quality_warning_windows
        build.first_window_start = result.first_window_start
        build.last_window_end = result.last_window_end
        build.elapsed_seconds = result.elapsed_seconds

    def _validate_configuration(
        self, lengths: list[int], stride: int, policy: WindowQualityPolicy, mode: str
    ) -> None:
        if not lengths or any(length <= 0 for length in lengths):
            raise ValueError("WINDOW_CONFIGURATION_INVALID")
        if stride <= 0:
            raise ValueError("WINDOW_CONFIGURATION_INVALID")
        if mode not in {"incremental", "full", "range"}:
            raise ValueError("WINDOW_CONFIGURATION_INVALID")
        if policy.mode not in {"strict", "allow_gaps"}:
            raise ValueError("WINDOW_CONFIGURATION_INVALID")
        if policy.calendar_mode not in {"continuous", "session_based", "unknown"}:
            raise ValueError("UNSUPPORTED_CALENDAR_POLICY")

    def _load_bars(
        self,
        instrument_id: str,
        timeframe_id: str,
        start_timestamp: datetime | None,
        end_timestamp: datetime | None,
    ) -> list[PriceBar]:
        query = select(PriceBar).where(
            PriceBar.instrument_id == instrument_id,
            PriceBar.timeframe_id == timeframe_id,
        )
        if start_timestamp is not None:
            query = query.where(PriceBar.timestamp >= start_timestamp)
        if end_timestamp is not None:
            query = query.where(PriceBar.timestamp <= end_timestamp)
        query = query.order_by(PriceBar.timestamp, PriceBar.id)
        return list(self.session.scalars(query))

    def _existing_window_keys(
        self, instrument_id: str, timeframe_id: str, lengths: list[int], window_version: str, configuration_hash: str
    ) -> set[tuple[datetime, int, str, str, str]]:
        rows = self.session.execute(
            select(
                PatternWindow.end_timestamp,
                PatternWindow.window_length,
                PatternWindow.window_version,
                PatternWindow.source_data_hash,
                PatternWindow.build_configuration_hash,
            ).where(
                PatternWindow.instrument_id == instrument_id,
                PatternWindow.timeframe_id == timeframe_id,
                PatternWindow.window_length.in_(lengths),
                PatternWindow.window_version == window_version,
                PatternWindow.build_configuration_hash == configuration_hash,
            )
        )
        return {(row[0], row[1], row[2], row[3], row[4]) for row in rows}

    def _latest_end_timestamp(
        self, instrument_id: str, timeframe_id: str, length: int, window_version: str, configuration_hash: str
    ) -> datetime | None:
        return self.session.scalar(
            select(PatternWindow.end_timestamp)
            .where(
                PatternWindow.instrument_id == instrument_id,
                PatternWindow.timeframe_id == timeframe_id,
                PatternWindow.window_length == length,
                PatternWindow.window_version == window_version,
                PatternWindow.build_configuration_hash == configuration_hash,
            )
            .order_by(PatternWindow.end_timestamp.desc())
            .limit(1)
        )

    def _quality_flags(self, bars: list[PriceBar], policy: WindowQualityPolicy) -> list[str]:
        flags: set[str] = set()
        if policy.calendar_mode == "unknown":
            flags.add(WindowQualityFlag.unknown_calendar.value)
        for bar in bars:
            if bar.volume is None:
                flags.add(WindowQualityFlag.null_volume.value)
            elif float(bar.volume) == 0:
                flags.add(WindowQualityFlag.zero_volume.value)
            if min(float(bar.open), float(bar.high), float(bar.low), float(bar.close)) <= 0:
                flags.add(WindowQualityFlag.invalid_ohlc.value)
            if float(bar.high) < max(float(bar.open), float(bar.low), float(bar.close)):
                flags.add(WindowQualityFlag.invalid_ohlc.value)
            if float(bar.low) > min(float(bar.open), float(bar.high), float(bar.close)):
                flags.add(WindowQualityFlag.invalid_ohlc.value)
        timestamps = [bar.timestamp for bar in bars]
        if timestamps != sorted(timestamps):
            flags.add(WindowQualityFlag.non_monotonic_timestamps.value)
        if len(set(timestamps)) != len(timestamps):
            flags.add(WindowQualityFlag.duplicate_timestamps.value)
        seconds = bars[0].timeframe.seconds if bars and bars[0].timeframe else None
        if seconds and policy.calendar_mode == "continuous":
            missing = 0
            for previous, current in pairwise(timestamps):
                delta_seconds = int((current - previous).total_seconds())
                if delta_seconds > seconds:
                    missing += max(0, (delta_seconds // seconds) - 1)
            if missing:
                flags.add(WindowQualityFlag.missing_bars.value)
                if missing / max(1, len(bars)) > policy.maximum_gap_ratio:
                    flags.add(WindowQualityFlag.extreme_gap.value)
        return sorted(flags) if flags else [WindowQualityFlag.none.value]

    def _reject_for_quality(self, flags: list[str], policy: WindowQualityPolicy) -> bool:
        if policy.mode == "allow_gaps":
            return False
        return any(flag in flags for flag in {WindowQualityFlag.missing_bars.value, WindowQualityFlag.extreme_gap.value})


def list_window_bars(session: Session, window: PatternWindow) -> list[PriceBar]:
    return list(
        session.scalars(
            select(PriceBar)
            .where(
                and_(
                    PriceBar.instrument_id == window.instrument_id,
                    PriceBar.timeframe_id == window.timeframe_id,
                    PriceBar.timestamp >= window.start_timestamp,
                    PriceBar.timestamp <= window.end_timestamp,
                )
            )
            .order_by(PriceBar.timestamp, PriceBar.id)
        )
    )
