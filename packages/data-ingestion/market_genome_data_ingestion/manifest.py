from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from market_genome_domain.models import DataImport
from market_genome_shared.hashing import sha256_canonical
from sqlalchemy import select
from sqlalchemy.orm import Session

from market_genome_data_ingestion.csv_import import (
    CsvImportMetadata,
    file_sha256,
    persist_csv_import,
)

REQUIRED_MANIFEST_FIELDS = {
    "symbol",
    "name",
    "asset_class",
    "exchange",
    "currency",
    "timezone",
    "timeframe",
    "source",
    "path",
    "volume_type",
    "price_adjustment",
    "minimum_rows",
}
PRICE_COLUMNS = ("open", "high", "low", "close")
CSV_COLUMNS = {"timestamp", *PRICE_COLUMNS, "volume"}


@dataclass(frozen=True)
class DatasetQualityReport:
    manifest_code: str
    dataset_code: str
    symbol: str
    path: str
    exists: bool
    rows_read: int = 0
    rows_accepted: int = 0
    rows_rejected: int = 0
    date_start: str | None = None
    date_end: str | None = None
    duplicates: int = 0
    out_of_order_rows: int = 0
    invalid_ohlc: int = 0
    missing_values: int = 0
    non_positive_prices: int = 0
    missing_volume_rate: float = 0.0
    zero_volume_rate: float = 0.0
    extreme_one_bar_returns: int = 0
    possible_split_events: int = 0
    possible_futures_roll_gaps: int = 0
    possible_bad_ticks: int = 0
    source_hash: str | None = None
    canonical_hash: str | None = None
    quality_decision: str = "REJECTED"
    import_id: str | None = None
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest_code": self.manifest_code,
            "dataset_code": self.dataset_code,
            "symbol": self.symbol,
            "path": self.path,
            "exists": self.exists,
            "rows_read": self.rows_read,
            "rows_accepted": self.rows_accepted,
            "rows_rejected": self.rows_rejected,
            "date_start": self.date_start,
            "date_end": self.date_end,
            "duplicates": self.duplicates,
            "out_of_order_rows": self.out_of_order_rows,
            "invalid_ohlc": self.invalid_ohlc,
            "missing_values": self.missing_values,
            "non_positive_prices": self.non_positive_prices,
            "missing_volume_rate": self.missing_volume_rate,
            "zero_volume_rate": self.zero_volume_rate,
            "extreme_one_bar_returns": self.extreme_one_bar_returns,
            "possible_split_events": self.possible_split_events,
            "possible_futures_roll_gaps": self.possible_futures_roll_gaps,
            "possible_bad_ticks": self.possible_bad_ticks,
            "source_hash": self.source_hash,
            "canonical_hash": self.canonical_hash,
            "quality_decision": self.quality_decision,
            "import_id": self.import_id,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def load_data_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("DATA_MANIFEST_INVALID_JSON_COMPATIBLE_YAML") from exc
    validate_data_manifest(manifest)
    manifest["_manifest_path"] = str(path)
    manifest["_manifest_hash"] = manifest_hash(manifest)
    return manifest


def manifest_hash(manifest: dict[str, Any]) -> str:
    clean = {key: value for key, value in manifest.items() if not key.startswith("_")}
    return sha256_canonical(clean)


PROVIDER_MANIFEST_CODES = {"yahoo_finance_v1", "alpha_vantage_v1"}


def validate_data_manifest(manifest: dict[str, Any]) -> None:
    if not manifest.get("manifest", {}).get("code"):
        raise ValueError("DATA_MANIFEST_CODE_REQUIRED")
    if "datasets" not in manifest and manifest.get("provider", {}).get("code") in PROVIDER_MANIFEST_CODES:
        manifest["datasets"] = datasets_from_provider_manifest(manifest)
    datasets = manifest.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("DATA_MANIFEST_DATASETS_REQUIRED")
    for index, dataset in enumerate(datasets):
        missing = REQUIRED_MANIFEST_FIELDS.difference(dataset)
        if missing:
            raise ValueError(f"DATASET_{index}_MISSING_FIELDS:{sorted(missing)}")


def dataset_code(dataset: dict[str, Any]) -> str:
    return str(dataset.get("code") or f"{dataset['symbol']}_{dataset['timeframe']}_{dataset['source']}")


PROVIDER_SOURCE_NAMES = {
    "yahoo_finance_v1": "YAHOO_FINANCE",
    "alpha_vantage_v1": "ALPHA_VANTAGE",
}


def datasets_from_provider_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    code = manifest["manifest"]["code"]
    provider_code = manifest["provider"]["code"]
    source_name = PROVIDER_SOURCE_NAMES.get(provider_code, provider_code.upper())
    data_root = os.environ.get("MARKET_GENOME_DATA_ROOT")
    base = Path(data_root) / "raw" / code if data_root else Path("../../data/raw") / code
    return [
        {
            "code": f"{item['canonical_symbol']}_{item['timeframe']}_{source_name}",
            "symbol": item["canonical_symbol"],
            "name": item["name"],
            "asset_class": item["asset_class"],
            "exchange": item["exchange"],
            "currency": item["currency"],
            "timezone": item["timezone"],
            "timeframe": item["timeframe"],
            "timeframe_seconds": 86_400,
            "source": source_name,
            "path": str(base / f"{item['canonical_symbol']}_{item['timeframe']}.csv"),
            "volume_type": item["volume_type"],
            "price_adjustment": item.get("price_adjustment_basis", "provider_auto_adjusted"),
            "minimum_rows": int(item.get("minimum_rows", manifest.get("quality_thresholds", {}).get("minimum_rows", 500))),
            "provider_symbol": item["provider_symbol"],
            "provider_code": provider_code,
        }
        for item in manifest.get("instruments", [])
        if item.get("enabled", True)
    ]


def analyze_dataset_quality(manifest: dict[str, Any], dataset: dict[str, Any]) -> DatasetQualityReport:
    manifest_path = Path(manifest.get("_manifest_path", ".")).resolve()
    path = Path(dataset["path"])
    if not path.is_absolute():
        path = (manifest_path.parent / path).resolve()
    code = dataset_code(dataset)
    manifest_code = manifest["manifest"]["code"]
    if not path.exists():
        return DatasetQualityReport(
            manifest_code=manifest_code,
            dataset_code=code,
            symbol=dataset["symbol"],
            path=str(path),
            exists=False,
            errors=("REAL_DATA_REQUIRED",),
            quality_decision="REJECTED",
        )
    source_hash = file_sha256(path)
    frame = pd.read_csv(path)
    errors: list[str] = []
    warnings: list[str] = []
    missing_columns = CSV_COLUMNS.difference(frame.columns)
    if missing_columns:
        return DatasetQualityReport(
            manifest_code=manifest_code,
            dataset_code=code,
            symbol=dataset["symbol"],
            path=str(path),
            exists=True,
            rows_read=len(frame),
            source_hash=source_hash,
            errors=(f"MISSING_COLUMNS:{sorted(missing_columns)}",),
            quality_decision="REJECTED",
        )

    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in (*PRICE_COLUMNS, "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    rows_read = len(frame)
    duplicates = int(frame["timestamp"].duplicated().sum())
    out_of_order = int((frame["timestamp"].diff().dt.total_seconds().fillna(1) < 0).sum())
    missing_values = int(frame[["timestamp", *PRICE_COLUMNS]].isna().any(axis=1).sum())
    missing_volume = int(frame["volume"].isna().sum())
    zero_volume = int((frame["volume"].fillna(1) == 0).sum())
    invalid_ohlc = int(
        (
            (frame["high"] < frame[["open", "low", "close"]].max(axis=1))
            | (frame["low"] > frame[["open", "high", "close"]].min(axis=1))
        ).sum()
    )
    non_positive = int((frame[list(PRICE_COLUMNS)] <= 0).any(axis=1).sum())
    returns = frame["close"].pct_change().abs()
    extreme_returns = int((returns > float(manifest.get("quality_thresholds", {}).get("extreme_return_threshold", 0.20))).sum())
    split_events = int((returns > float(manifest.get("quality_thresholds", {}).get("split_event_threshold", 0.45))).sum())
    bad_ticks = int((returns > float(manifest.get("quality_thresholds", {}).get("bad_tick_threshold", 0.60))).sum())
    deltas = frame["timestamp"].diff().dropna()
    possible_roll_gaps = int((deltas > deltas.mode().iloc[0] * 3).sum()) if not deltas.empty else 0

    hard_rejections = duplicates + out_of_order + missing_values + invalid_ohlc + non_positive
    rows_rejected = hard_rejections
    rows_accepted = max(0, rows_read - rows_rejected)
    minimum_rows = int(dataset["minimum_rows"])
    if missing_volume:
        warnings.append("NULL_VOLUME_PRESERVED_IN_QUALITY_REPORT_SCHEMA_IMPORT_LIMITED")
    if dataset.get("provider_code") in {"yahoo_finance_v1", "alpha_vantage_v1"}:
        warnings.append("PROVIDER_DATA_RESEARCH_ONLY")
        if dataset.get("provider_code") == "yahoo_finance_v1":
            warnings.append("POSSIBLE_RETROACTIVE_PROVIDER_REVISION")
        if "provider" in str(dataset.get("price_adjustment", "")):
            warnings.append("PRICE_ADJUSTMENT_PROVIDER_CONTROLLED")
        asset_class = str(dataset.get("asset_class", "")).lower()
        provider_symbol = dataset.get("provider_symbol", "")
        if "future" in asset_class or provider_symbol.endswith("=F"):
            warnings.append("FUTURES_CONTINUOUS_CONTRACT_UNVERIFIED")
        if asset_class == "forex" or provider_symbol.endswith("=X"):
            warnings.append("FOREX_VOLUME_UNAVAILABLE")
        if asset_class == "crypto" or "-" in provider_symbol:
            warnings.append("CRYPTO_SINGLE_VENUE_OR_AGGREGATED_SOURCE")
    if extreme_returns:
        warnings.append("EXTREME_ONE_BAR_RETURNS")
    if split_events:
        warnings.append("POSSIBLE_SPLIT_EVENTS")
    if possible_roll_gaps:
        warnings.append("POSSIBLE_FUTURES_ROLL_GAPS")
    if bad_ticks:
        warnings.append("POSSIBLE_BAD_TICKS")
    if rows_accepted < minimum_rows:
        errors.append("INSUFFICIENT_ROWS")
    if hard_rejections:
        errors.append("INVALID_ROWS_PRESENT")

    if errors:
        decision = "REJECTED" if rows_accepted == 0 else "MANUAL_REVIEW_REQUIRED"
    elif warnings:
        decision = "ACCEPTED_WITH_WARNINGS"
    else:
        decision = "ACCEPTED"

    canonical_payload = {
        "dataset": {key: dataset[key] for key in sorted(REQUIRED_MANIFEST_FIELDS)},
        "source_hash": source_hash,
        "rows_read": rows_read,
        "rows_accepted": rows_accepted,
        "date_start": None if frame.empty else frame["timestamp"].min().isoformat(),
        "date_end": None if frame.empty else frame["timestamp"].max().isoformat(),
    }
    return DatasetQualityReport(
        manifest_code=manifest_code,
        dataset_code=code,
        symbol=dataset["symbol"],
        path=str(path),
        exists=True,
        rows_read=rows_read,
        rows_accepted=rows_accepted,
        rows_rejected=rows_rejected,
        date_start=canonical_payload["date_start"],
        date_end=canonical_payload["date_end"],
        duplicates=duplicates,
        out_of_order_rows=out_of_order,
        invalid_ohlc=invalid_ohlc,
        missing_values=missing_values,
        non_positive_prices=non_positive,
        missing_volume_rate=missing_volume / max(1, rows_read),
        zero_volume_rate=zero_volume / max(1, rows_read),
        extreme_one_bar_returns=extreme_returns,
        possible_split_events=split_events,
        possible_futures_roll_gaps=possible_roll_gaps,
        possible_bad_ticks=bad_ticks,
        source_hash=source_hash,
        canonical_hash=sha256_canonical(canonical_payload),
        quality_decision=decision,
        errors=tuple(errors),
        warnings=tuple(sorted(set(warnings))),
    )


def analyze_manifest_quality(manifest: dict[str, Any]) -> list[DatasetQualityReport]:
    return [analyze_dataset_quality(manifest, dataset) for dataset in manifest["datasets"]]


def import_manifest(session: Session, manifest: dict[str, Any], *, dry_run: bool) -> list[DatasetQualityReport]:
    reports = []
    for dataset in manifest["datasets"]:
        report = analyze_dataset_quality(manifest, dataset)
        if report.quality_decision in {"REJECTED", "MANUAL_REVIEW_REQUIRED"}:
            reports.append(report)
            continue
        if dry_run:
            reports.append(report)
            continue
        result = persist_csv_import(
            session,
            report.path,
            CsvImportMetadata(
                symbol=dataset["symbol"],
                instrument_name=dataset["name"],
                asset_class=dataset["asset_class"],
                exchange=dataset["exchange"],
                currency=dataset["currency"],
                timezone=dataset["timezone"],
                timeframe=dataset["timeframe"],
                source_name=dataset["source"],
                timeframe_seconds=int(dataset.get("timeframe_seconds") or 86_400),
                volume_type=dataset.get("volume_type"),
                dry_run=False,
            ),
        )
        result.data_import.configuration = {
            **result.data_import.configuration,
            "manifest_code": manifest["manifest"]["code"],
            "manifest_hash": manifest_hash(manifest),
            "dataset_code": report.dataset_code,
            "canonical_hash": report.canonical_hash,
            "quality_decision": report.quality_decision,
            "price_adjustment": dataset["price_adjustment"],
        }
        session.commit()
        reports.append(DatasetQualityReport(**{**report.as_dict(), "import_id": result.data_import.id}))
    return reports


def quality_reports_for_manifest(session: Session, manifest_code: str) -> list[dict[str, Any]]:
    rows = session.scalars(select(DataImport).order_by(DataImport.created_at).limit(10_000))
    return [
        {
            "import_id": row.id,
            "status": row.status,
            "rows_read": row.rows_read,
            "rows_valid": row.rows_valid,
            "rows_inserted": row.rows_inserted,
            "source_hash": row.source_hash,
            "canonical_hash": row.configuration.get("canonical_hash"),
            "quality_decision": row.configuration.get("quality_decision"),
            "dataset_code": row.configuration.get("dataset_code"),
        }
        for row in rows
        if row.configuration.get("manifest_code") == manifest_code
    ]


def write_quality_csv(path: Path, reports: list[DatasetQualityReport | dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [report.as_dict() if isinstance(report, DatasetQualityReport) else report for report in reports]
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def real_data_available(reports: list[DatasetQualityReport]) -> bool:
    return any(report.quality_decision in {"ACCEPTED", "ACCEPTED_WITH_WARNINGS"} for report in reports)
