from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from typing import Any

import pandas as pd
from market_genome_domain.models import (
    DataImport,
    DataImportIssue,
    DataSource,
    Instrument,
    PriceBar,
    Timeframe,
)
from market_genome_domain.registry import RegistryService
from market_genome_shared.hashing import sha256_canonical
from sqlalchemy import select
from sqlalchemy.orm import Session

REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}
PRICE_COLUMNS = ["open", "high", "low", "close"]


@dataclass(frozen=True)
class RowIssue:
    row_number: int
    severity: str
    code: str
    message: str


@dataclass
class ImportReport:
    source_hash: str
    rows_seen: int
    rows_valid: int
    rows_rejected: int
    warnings: list[RowIssue] = field(default_factory=list)
    errors: list[RowIssue] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.rows_valid > 0 and not self.errors


@dataclass(frozen=True)
class CsvImportMetadata:
    symbol: str
    instrument_name: str | None
    asset_class: str
    exchange: str | None
    currency: str | None
    timezone: str
    timeframe: str
    source_name: str
    timeframe_seconds: int | None = None
    tick_size: float | None = None
    price_precision: int | None = None
    volume_type: str | None = None
    duplicate_policy: str = "skip"
    dry_run: bool = False


@dataclass(frozen=True)
class PersistedImportResult:
    data_import: DataImport
    instrument: Instrument
    timeframe: Timeframe
    source: DataSource


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_ohlcv_csv(path: str | Path) -> tuple[pd.DataFrame, ImportReport]:
    csv_path = Path(path)
    source_hash = file_sha256(csv_path)
    frame = pd.read_csv(csv_path)
    issues: list[RowIssue] = []
    errors: list[RowIssue] = []

    missing = REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")

    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in [*PRICE_COLUMNS, "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    valid_mask = pd.Series(True, index=frame.index)
    previous_timestamp = None
    seen_timestamps: set[Any] = set()

    for index, row in frame.iterrows():
        row_number = int(index) + 2
        row_flags: list[RowIssue] = []

        if pd.isna(row["timestamp"]):
            row_flags.append(RowIssue(row_number, "error", "invalid_timestamp", "Timestamp is missing or invalid."))
        elif row["timestamp"] in seen_timestamps:
            row_flags.append(RowIssue(row_number, "error", "duplicate_timestamp", "Duplicate timestamp."))
        elif previous_timestamp is not None and row["timestamp"] < previous_timestamp:
            row_flags.append(RowIssue(row_number, "error", "out_of_order", "Timestamp is out of order."))

        if not pd.isna(row["timestamp"]):
            seen_timestamps.add(row["timestamp"])
            previous_timestamp = row["timestamp"]

        for column in [*PRICE_COLUMNS, "volume"]:
            value = row[column]
            if pd.isna(value) or not math.isfinite(float(value)):
                row_flags.append(RowIssue(row_number, "error", f"invalid_{column}", f"{column} is non-finite."))

        if row_flags:
            valid_mask.loc[index] = False
            errors.extend(row_flags)
            continue

        if min(float(row[column]) for column in PRICE_COLUMNS) <= 0:
            row_flags.append(RowIssue(row_number, "error", "non_positive_price", "OHLC prices must be positive."))
        if float(row["volume"]) < 0:
            row_flags.append(RowIssue(row_number, "error", "negative_volume", "Volume must be non-negative."))
        if float(row["high"]) < max(float(row["open"]), float(row["close"]), float(row["low"])):
            row_flags.append(RowIssue(row_number, "error", "invalid_high", "High is below open, low, or close."))
        if float(row["low"]) > min(float(row["open"]), float(row["close"]), float(row["high"])):
            row_flags.append(RowIssue(row_number, "error", "invalid_low", "Low is above open, high, or close."))

        if row_flags:
            valid_mask.loc[index] = False
            errors.extend(row_flags)

    valid = frame[valid_mask].reset_index(drop=True)
    if not valid.empty:
        deltas = valid["timestamp"].diff().dropna()
        if not deltas.empty:
            expected_delta = deltas.mode().iloc[0]
            missing_count = int((deltas > expected_delta).sum())
            if missing_count:
                issues.append(
                    RowIssue(0, "warning", "missing_bars", f"Detected {missing_count} timestamp gaps.")
                )

    report = ImportReport(
        source_hash=source_hash,
        rows_seen=len(frame),
        rows_valid=len(valid),
        rows_rejected=len(frame) - len(valid),
        warnings=issues,
        errors=errors,
    )
    return valid, report


def import_configuration_hash(metadata: CsvImportMetadata) -> str:
    return sha256_canonical(
        {
            "symbol": metadata.symbol,
            "instrument_name": metadata.instrument_name,
            "asset_class": metadata.asset_class,
            "exchange": metadata.exchange,
            "currency": metadata.currency,
            "timezone": metadata.timezone,
            "timeframe": metadata.timeframe,
            "source_name": metadata.source_name,
            "timeframe_seconds": metadata.timeframe_seconds,
            "tick_size": metadata.tick_size,
            "price_precision": metadata.price_precision,
            "volume_type": metadata.volume_type,
            "duplicate_policy": metadata.duplicate_policy,
            "dry_run": metadata.dry_run,
            "version": "csv_import_v1",
        }
    )


def upsert_registry(
    session: Session,
    symbol: str,
    timeframe_code: str,
    source_name: str,
    timeframe_seconds: int,
) -> tuple[Instrument, Timeframe, DataSource]:
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol))
    if instrument is None:
        instrument = Instrument(symbol=symbol, name=symbol)
        session.add(instrument)

    timeframe = session.scalar(select(Timeframe).where(Timeframe.code == timeframe_code))
    if timeframe is None:
        timeframe = Timeframe(
            code=timeframe_code,
            seconds=timeframe_seconds,
            label=timeframe_code,
            is_intraday=timeframe_seconds < 86_400,
        )
        session.add(timeframe)

    source = session.scalar(select(DataSource).where(DataSource.name == source_name))
    if source is None:
        source = DataSource(name=source_name, source_type="csv")
        session.add(source)

    session.flush()
    return instrument, timeframe, source


def persist_csv_import(
    session: Session,
    path: str | Path,
    metadata: CsvImportMetadata,
) -> PersistedImportResult:
    if metadata.duplicate_policy not in {"skip"}:
        raise ValueError("Only duplicate_policy='skip' is supported in this phase.")

    frame, report = validate_ohlcv_csv(path)
    registry = RegistryService(session)
    instrument = registry.create_instrument(
        symbol=metadata.symbol,
        name=metadata.instrument_name,
        asset_class=metadata.asset_class,
        exchange=metadata.exchange,
        currency=metadata.currency,
        timezone=metadata.timezone,
        tick_size=metadata.tick_size,
        price_precision=metadata.price_precision,
        volume_type=metadata.volume_type,
    )
    timeframe = registry.create_timeframe(
        code=metadata.timeframe,
        seconds=metadata.timeframe_seconds,
        label=metadata.timeframe,
    )
    source = registry.create_source(metadata.source_name, source_type="csv")
    config_hash = import_configuration_hash(metadata)

    existing_import = session.scalar(
        select(DataImport).where(
            DataImport.source_hash == report.source_hash,
            DataImport.configuration_hash == config_hash,
        )
    )
    if existing_import and not metadata.dry_run:
        return PersistedImportResult(existing_import, instrument, timeframe, source)

    inserted = 0
    skipped = 0
    existing_timestamps: set[Any] = set()
    if not metadata.dry_run and not frame.empty:
        existing_timestamps = set(
            session.scalars(
                select(PriceBar.timestamp).where(
                    PriceBar.instrument_id == instrument.id,
                    PriceBar.timeframe_id == timeframe.id,
                    PriceBar.source_id == source.id,
                )
            )
        )

    if not metadata.dry_run:
        for _, row in frame.iterrows():
            timestamp = row["timestamp"].to_pydatetime().astimezone(UTC)
            if timestamp in existing_timestamps:
                skipped += 1
                continue
            session.add(
                PriceBar(
                    instrument_id=instrument.id,
                    timeframe_id=timeframe.id,
                    source_id=source.id,
                    timestamp=timestamp,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    data_quality_flags=[],
                )
            )
            inserted += 1
            existing_timestamps.add(timestamp)
    else:
        skipped = report.rows_valid

    quality = {
        "missing_bar_count": sum(1 for issue in report.warnings if issue.code == "missing_bars"),
        "duplicate_count": sum(1 for issue in report.errors if issue.code == "duplicate_timestamp"),
        "out_of_order_count": sum(1 for issue in report.errors if issue.code == "out_of_order"),
        "invalid_ohlc_count": sum(1 for issue in report.errors if issue.code in {"invalid_high", "invalid_low"}),
    }
    status = "completed"
    if report.errors:
        status = "completed_with_errors" if inserted or metadata.dry_run else "failed"
    elif report.warnings:
        status = "completed_with_warnings"

    data_import = DataImport(
        instrument_id=instrument.id,
        timeframe_id=timeframe.id,
        source_id=source.id,
        source_hash=report.source_hash,
        configuration_hash=config_hash,
        status=status,
        dry_run=metadata.dry_run,
        rows_read=report.rows_seen,
        rows_valid=report.rows_valid,
        rows_inserted=inserted,
        rows_updated=0,
        rows_skipped=skipped,
        warnings_count=len(report.warnings),
        errors_count=len(report.errors),
        quality_summary=quality,
        configuration={
            "symbol": metadata.symbol,
            "exchange": metadata.exchange,
            "timeframe": metadata.timeframe,
            "source_name": metadata.source_name,
            "duplicate_policy": metadata.duplicate_policy,
        },
    )
    session.add(data_import)
    session.flush()
    for issue in [*report.warnings, *report.errors]:
        session.add(
            DataImportIssue(
                import_id=data_import.id,
                row_number=issue.row_number,
                severity=issue.severity,
                issue_type=issue.code,
                message=issue.message,
            )
        )
    session.commit()
    session.refresh(data_import)
    return PersistedImportResult(data_import, instrument, timeframe, source)


def import_ohlcv_csv(
    session: Session,
    path: str | Path,
    symbol: str,
    timeframe_code: str,
    timeframe_seconds: int,
    source_name: str = "csv",
) -> ImportReport:
    frame, report = validate_ohlcv_csv(path)
    instrument, timeframe, source = upsert_registry(
        session, symbol, timeframe_code, source_name, timeframe_seconds
    )

    for _, row in frame.iterrows():
        timestamp = row["timestamp"].to_pydatetime().astimezone(UTC)
        existing = session.scalar(
            select(PriceBar).where(
                PriceBar.instrument_id == instrument.id,
                PriceBar.timeframe_id == timeframe.id,
                PriceBar.source_id == source.id,
                PriceBar.timestamp == timestamp,
            )
        )
        if existing is not None:
            existing.data_quality_flags = sorted(set(existing.data_quality_flags + ["duplicate_on_import"]))
            continue

        session.add(
            PriceBar(
                instrument_id=instrument.id,
                timeframe_id=timeframe.id,
                source_id=source.id,
                timestamp=timestamp,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                data_quality_flags=[],
            )
        )

    session.commit()
    return report
