from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from market_genome_shared.hashing import sha256_canonical

from market_genome_data_ingestion.csv_import import file_sha256
from market_genome_data_ingestion.providers.base import HistoricalDataRequest, HistoricalDataResult

PRICE_COLUMNS = ("open", "high", "low", "close")
YAHOO_INTERVALS = {"D1": "1d"}
RESEARCH_WARNINGS = {
    "PROVIDER_DATA_RESEARCH_ONLY",
    "POSSIBLE_RETROACTIVE_PROVIDER_REVISION",
    "PRICE_ADJUSTMENT_PROVIDER_CONTROLLED",
}


class YahooFinanceProvider:
    code = "yahoo_finance_v1"
    version = "provider_v1"
    classification = "PILOT_AND_RESEARCH_SOURCE"
    client_name = "yfinance"

    def __init__(self, downloader: Callable[..., pd.DataFrame] | None = None):
        self._downloader = downloader

    @property
    def client_version(self) -> str:
        try:
            return importlib.metadata.version("yfinance")
        except importlib.metadata.PackageNotFoundError:
            return "not-installed"

    def fetch(self, request: HistoricalDataRequest) -> HistoricalDataResult:
        interval = self._interval(request.timeframe)
        csv_path = self._csv_path(request)
        provenance_path = csv_path.with_suffix(".provenance.json")
        warnings = sorted(self._source_warnings(request))
        if csv_path.exists() or provenance_path.exists():
            return self._handle_existing(request, csv_path, provenance_path, interval, warnings)

        downloader = self._downloader or self._load_downloader()
        frame = self._download_with_retries(downloader, request, interval)
        canonical = canonicalize_yahoo_frame(frame)
        self._validate_canonical(canonical, request)
        raw_hash = dataframe_hash(frame)
        csv_hash = canonical_csv_hash(canonical)

        request.output_directory.mkdir(parents=True, exist_ok=True)
        canonical.to_csv(csv_path, index=False, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        actual_hash = file_sha256(csv_path)
        if actual_hash != csv_hash:
            raise ValueError("HASH_FAILED")
        provenance = self._provenance(request, canonical, raw_hash, csv_hash, warnings, "COMPLETED")
        provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True), encoding="utf-8")
        return self._result(request, canonical, raw_hash, csv_hash, csv_path, provenance_path, warnings, "COMPLETED")

    def dry_run(self, request: HistoricalDataRequest) -> dict[str, Any]:
        interval = self._interval(request.timeframe)
        csv_path = self._csv_path(request)
        provenance_path = csv_path.with_suffix(".provenance.json")
        return {
            "provider": self.code,
            "client": self.client_name,
            "client_version": self.client_version,
            "provider_symbol": request.provider_symbol,
            "canonical_symbol": request.canonical_symbol,
            "requested_start": request.start,
            "requested_end": request.end,
            "interval": interval,
            "auto_adjust": request.auto_adjust,
            "actions_requested": request.include_actions,
            "delay_seconds": request.delay_seconds,
            "maximum_retries": request.maximum_retries,
            "csv_path": str(csv_path),
            "provenance_path": str(provenance_path),
            "exists": csv_path.exists() or provenance_path.exists(),
            "status": "DRY_RUN",
        }

    def _load_downloader(self) -> Callable[..., pd.DataFrame]:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError("YFINANCE_NOT_INSTALLED") from exc
        return yf.download

    def _download_with_retries(
        self,
        downloader: Callable[..., pd.DataFrame],
        request: HistoricalDataRequest,
        interval: str,
    ) -> pd.DataFrame:
        delay = request.initial_retry_delay
        last_error: Exception | None = None
        for attempt in range(request.maximum_retries + 1):
            if attempt:
                time.sleep(min(delay, request.maximum_retry_delay))
                delay *= request.backoff_multiplier
            try:
                frame = downloader(
                    request.provider_symbol,
                    start=request.start,
                    end=request.end,
                    interval=interval,
                    auto_adjust=request.auto_adjust,
                    actions=request.include_actions,
                    progress=False,
                    threads=False,
                )
                if frame is None or frame.empty:
                    raise ValueError("EMPTY_RESPONSE")
                time.sleep(max(0.0, request.delay_seconds))
                return frame
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        if isinstance(last_error, ValueError):
            raise last_error
        raise RuntimeError("PROVIDER_UNAVAILABLE") from last_error

    def _handle_existing(
        self,
        request: HistoricalDataRequest,
        csv_path: Path,
        provenance_path: Path,
        interval: str,
        warnings: list[str],
    ) -> HistoricalDataResult:
        if not csv_path.exists() or not provenance_path.exists():
            raise ValueError("IMMUTABLE_ACQUISITION_INCOMPLETE")
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        actual_hash = file_sha256(csv_path)
        if actual_hash != provenance.get("canonical_csv_hash"):
            raise ValueError("IMMUTABLE_ACQUISITION_HASH_MISMATCH")
        expected = self._configuration_hash(request)
        if provenance.get("acquisition_configuration_hash") != expected and not (
            request.force_refresh and request.new_version
        ):
            raise ValueError("IMMUTABLE_ACQUISITION_CONFIGURATION_MISMATCH")
        if request.force_refresh and request.new_version:
            return self.fetch(HistoricalDataRequest(**{**asdict(request), "dataset_version": request.new_version, "force_refresh": False, "new_version": None}))
        frame = pd.read_csv(csv_path)
        return self._result(
            request,
            frame,
            provenance.get("raw_dataframe_hash"),
            actual_hash,
            csv_path,
            provenance_path,
            warnings,
            "SKIPPED_EXISTING",
            interval=interval,
        )

    def _csv_path(self, request: HistoricalDataRequest) -> Path:
        suffix = "" if request.dataset_version == "v1" else f"_{request.dataset_version}"
        return request.output_directory / f"{request.canonical_symbol}_{request.timeframe}{suffix}.csv"

    def _interval(self, timeframe: str) -> str:
        if timeframe not in YAHOO_INTERVALS:
            raise ValueError("UNSUPPORTED_INTERVAL")
        return YAHOO_INTERVALS[timeframe]

    def _validate_canonical(self, frame: pd.DataFrame, request: HistoricalDataRequest) -> None:
        if frame.empty:
            raise ValueError("EMPTY_RESPONSE")
        if frame["timestamp"].isna().any():
            raise ValueError("CANONICALIZATION_FAILED")
        if frame["timestamp"].duplicated().any():
            raise ValueError("DUPLICATE_TIMESTAMPS")
        if not frame["timestamp"].is_monotonic_increasing:
            raise ValueError("CANONICALIZATION_FAILED")
        if frame[list(PRICE_COLUMNS)].isna().any().any():
            raise ValueError("CANONICALIZATION_FAILED")
        if (frame[list(PRICE_COLUMNS)] <= 0).any().any():
            raise ValueError("NON_POSITIVE_PRICES")
        if (frame["high"] < frame[["open", "low", "close"]].max(axis=1)).any():
            raise ValueError("CANONICALIZATION_FAILED")
        if (frame["low"] > frame[["open", "high", "close"]].min(axis=1)).any():
            raise ValueError("CANONICALIZATION_FAILED")
        if len(frame) < 1:
            raise ValueError("TRUNCATED_RESPONSE")

    def _source_warnings(self, request: HistoricalDataRequest) -> set[str]:
        warnings = set(RESEARCH_WARNINGS)
        asset = request.asset_class.lower()
        if "future" in asset or request.provider_symbol.endswith("=F"):
            warnings.add("FUTURES_CONTINUOUS_CONTRACT_UNVERIFIED")
        if "forex" in asset or request.provider_symbol.endswith("=X"):
            warnings.add("FOREX_VOLUME_UNAVAILABLE")
        if "crypto" in asset or "-" in request.provider_symbol:
            warnings.add("CRYPTO_SINGLE_VENUE_OR_AGGREGATED_SOURCE")
        return warnings

    def _configuration_hash(self, request: HistoricalDataRequest) -> str:
        return sha256_canonical(
            {
                "provider": self.code,
                "provider_symbol": request.provider_symbol,
                "canonical_symbol": request.canonical_symbol,
                "timeframe": request.timeframe,
                "start": request.start,
                "end": request.end,
                "auto_adjust": request.auto_adjust,
                "include_actions": request.include_actions,
                "dataset_version": request.dataset_version,
            }
        )

    def _provenance(
        self,
        request: HistoricalDataRequest,
        frame: pd.DataFrame,
        raw_hash: str,
        csv_hash: str,
        warnings: list[str],
        status: str,
    ) -> dict[str, Any]:
        return {
            "provider": self.code,
            "provider_version": self.version,
            "provider_classification": self.classification,
            "provider_symbol": request.provider_symbol,
            "canonical_symbol": request.canonical_symbol,
            "client": self.client_name,
            "client_version": self.client_version,
            "interval": self._interval(request.timeframe),
            "requested_start": request.start,
            "requested_end": request.end,
            "received_start": None if frame.empty else str(frame["timestamp"].iloc[0]),
            "received_end": None if frame.empty else str(frame["timestamp"].iloc[-1]),
            "downloaded_at": datetime.now(UTC).isoformat(),
            "auto_adjust": request.auto_adjust,
            "actions_requested": request.include_actions,
            "split_adjusted": request.auto_adjust,
            "dividend_adjusted": request.auto_adjust,
            "volume_type": request.volume_type,
            "price_adjustment_basis": request.price_adjustment_basis,
            "row_count": len(frame),
            "raw_dataframe_hash": raw_hash,
            "canonical_csv_hash": csv_hash,
            "acquisition_configuration_hash": self._configuration_hash(request),
            "warnings": warnings,
            "status": status,
            "python_version": sys.version,
            "operating_system": platform.platform(),
            "market_genome_code_version": self._git_revision(),
            "working_tree_dirty": self._git_dirty(),
        }

    def _result(
        self,
        request: HistoricalDataRequest,
        frame: pd.DataFrame,
        raw_hash: str | None,
        csv_hash: str | None,
        csv_path: Path | None,
        provenance_path: Path | None,
        warnings: list[str],
        status: str,
        *,
        interval: str | None = None,
    ) -> HistoricalDataResult:
        return HistoricalDataResult(
            provider_code=self.code,
            provider_version=self.version,
            client_name=self.client_name,
            client_version=self.client_version,
            provider_symbol=request.provider_symbol,
            canonical_symbol=request.canonical_symbol,
            requested_start=request.start,
            requested_end=request.end,
            received_start=None if frame.empty else str(frame["timestamp"].iloc[0]),
            received_end=None if frame.empty else str(frame["timestamp"].iloc[-1]),
            interval=interval or self._interval(request.timeframe),
            row_count=len(frame),
            raw_dataframe_hash=raw_hash,
            canonical_csv_hash=csv_hash,
            csv_path=None if csv_path is None else str(csv_path),
            provenance_path=None if provenance_path is None else str(provenance_path),
            warnings=warnings,
            status=status,
        )

    def _git_revision(self) -> str | None:
        try:
            return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=False).stdout.strip() or None
        except Exception:  # noqa: BLE001
            return None

    def _git_dirty(self) -> bool | None:
        try:
            return bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=5, check=False).stdout.strip())
        except Exception:  # noqa: BLE001
            return None


def canonicalize_yahoo_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.copy()
        frame.columns = [str(parts[0]).lower().replace(" ", "_") for parts in frame.columns]
    else:
        frame = frame.rename(columns={column: str(column).lower().replace(" ", "_") for column in frame.columns})
    frame = frame.reset_index()
    frame = frame.rename(columns={column: str(column).lower().replace(" ", "_") for column in frame.columns})
    frame = frame.rename(columns={"date": "timestamp", "datetime": "timestamp"})
    if "adj_close" in frame.columns and "close" not in frame.columns:
        frame["close"] = frame["adj_close"]
    required = {"timestamp", "open", "high", "low", "close"}
    if missing := required.difference(frame.columns):
        raise ValueError(f"CANONICALIZATION_FAILED:{sorted(missing)}")
    if "volume" not in frame.columns:
        frame["volume"] = 0
    canonical = frame[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    canonical["timestamp"] = pd.to_datetime(canonical["timestamp"], utc=True, errors="coerce")
    for column in PRICE_COLUMNS:
        canonical[column] = pd.to_numeric(canonical[column], errors="coerce")
    complete_price_rows = ~canonical[list(PRICE_COLUMNS)].isna().any(axis=1)
    if complete_price_rows.any():
        canonical.loc[complete_price_rows, "high"] = canonical.loc[complete_price_rows, list(PRICE_COLUMNS)].max(axis=1)
        canonical.loc[complete_price_rows, "low"] = canonical.loc[complete_price_rows, list(PRICE_COLUMNS)].min(axis=1)
    canonical["volume"] = pd.to_numeric(canonical["volume"], errors="coerce")
    if canonical["volume"].isna().any():
        canonical["volume"] = canonical["volume"].fillna(0)
    canonical = canonical.sort_values("timestamp").reset_index(drop=True)
    canonical["timestamp"] = canonical["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    return canonical


def dataframe_hash(frame: pd.DataFrame) -> str:
    normalized = frame.copy()
    if isinstance(normalized.columns, pd.MultiIndex):
        normalized.columns = ["|".join(str(part) for part in parts) for parts in normalized.columns]
    return sha256_canonical(json.loads(normalized.reset_index().to_json(orient="records", date_format="iso")))


def canonical_csv_hash(frame: pd.DataFrame) -> str:
    content = frame.to_csv(index=False, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
