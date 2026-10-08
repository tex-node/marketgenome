from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
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
ALPHA_VANTAGE_INTERVALS = {"D1": "daily"}
API_KEY_ENV_VAR = "ALPHA_VANTAGE_API_KEY"
API_ENDPOINT = "https://www.alphavantage.co/query"
RESEARCH_WARNINGS = {
    "PROVIDER_DATA_RESEARCH_ONLY",
    "PRICE_ADJUSTMENT_PROVIDER_UNADJUSTED_RAW",
}
FIELD_PATTERNS = {
    "open": re.compile(r"open", re.IGNORECASE),
    "high": re.compile(r"high", re.IGNORECASE),
    "low": re.compile(r"low", re.IGNORECASE),
    "close": re.compile(r"close", re.IGNORECASE),
    "volume": re.compile(r"volume", re.IGNORECASE),
}
NOT_USD_CURRENCY_HINT = re.compile(r"\((?!USD\)|usd\))[A-Za-z]{3}\)", re.IGNORECASE)

FUNCTION_BY_ASSET_CLASS = {
    "equity_etf": "TIME_SERIES_DAILY",
    "forex": "FX_DAILY",
    "crypto": "DIGITAL_CURRENCY_DAILY",
}
UNSUPPORTED_ASSET_CLASSES = {"commodity", "commodity_future_proxy", "futures"}


class AlphaVantageProviderError(RuntimeError):
    pass


class AlphaVantageProvider:
    code = "alpha_vantage_v1"
    version = "provider_v1"
    classification = "INDEPENDENT_PUBLIC_MARKET_DATA_PROVIDER"
    provider_independence = "CONFIRMED"
    client_name = "alpha_vantage_http"
    client_version = "http_v1"

    def __init__(self, fetcher: Callable[[dict[str, str]], dict[str, Any]] | None = None):
        self._fetcher = fetcher

    def fetch(self, request: HistoricalDataRequest) -> HistoricalDataResult:
        function = self._function(request)
        csv_path = self._csv_path(request)
        provenance_path = csv_path.with_suffix(".provenance.json")
        warnings = sorted(self._source_warnings(request))
        if csv_path.exists() or provenance_path.exists():
            return self._handle_existing(request, csv_path, provenance_path, warnings)

        fetcher = self._fetcher or self._http_fetcher
        payload = self._download_with_retries(fetcher, request, function)
        canonical = canonicalize_alpha_vantage_payload(payload, function, request.asset_class)
        self._validate_canonical(canonical, request)
        raw_hash = sha256_canonical(payload)
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
        function = self._function(request)
        csv_path = self._csv_path(request)
        provenance_path = csv_path.with_suffix(".provenance.json")
        key_present = bool(os.environ.get(API_KEY_ENV_VAR))
        return {
            "provider": self.code,
            "provider_independence": self.provider_independence,
            "client": self.client_name,
            "function": function,
            "provider_symbol": request.provider_symbol,
            "canonical_symbol": request.canonical_symbol,
            "requested_start": request.start,
            "requested_end": request.end,
            "api_key_configured": key_present,
            "delay_seconds": request.delay_seconds,
            "maximum_retries": request.maximum_retries,
            "csv_path": str(csv_path),
            "provenance_path": str(provenance_path),
            "exists": csv_path.exists() or provenance_path.exists(),
            "status": "DRY_RUN" if key_present else "DRY_RUN_MISSING_API_KEY",
        }

    def _function(self, request: HistoricalDataRequest) -> str:
        if request.timeframe not in ALPHA_VANTAGE_INTERVALS:
            raise ValueError("UNSUPPORTED_INTERVAL")
        asset = request.asset_class.lower()
        if asset in UNSUPPORTED_ASSET_CLASSES:
            raise ValueError("UNSUPPORTED_ASSET_CLASS_ALPHA_VANTAGE_NO_DAILY_OHLC")
        function = FUNCTION_BY_ASSET_CLASS.get(asset)
        if function is None:
            raise ValueError("UNSUPPORTED_ASSET_CLASS_ALPHA_VANTAGE")
        return function

    def _http_fetcher(self, params: dict[str, str]) -> dict[str, Any]:
        api_key = os.environ.get(API_KEY_ENV_VAR)
        if not api_key:
            raise AlphaVantageProviderError("ALPHA_VANTAGE_API_KEY_NOT_CONFIGURED")
        query = dict(params)
        query["apikey"] = api_key
        url = f"{API_ENDPOINT}?{urllib.parse.urlencode(query)}"
        request_obj = urllib.request.Request(url, headers={"User-Agent": "market-genome-research/1.0"})
        with urllib.request.urlopen(request_obj, timeout=30) as response:
            body = response.read().decode("utf-8")
        return json.loads(body)

    def _download_with_retries(
        self,
        fetcher: Callable[[dict[str, str]], dict[str, Any]],
        request: HistoricalDataRequest,
        function: str,
    ) -> dict[str, Any]:
        params = self._request_params(request, function)
        delay = request.initial_retry_delay
        last_error: Exception | None = None
        for attempt in range(request.maximum_retries + 1):
            if attempt:
                time.sleep(min(delay, request.maximum_retry_delay))
                delay *= request.backoff_multiplier
            try:
                payload = fetcher(params)
                self._raise_for_provider_error(payload)
                time.sleep(max(0.0, request.delay_seconds))
                return payload
            except AlphaVantageProviderError:
                # Definitive provider-level rejections (rate limit, premium-only endpoint,
                # bad symbol) will not be fixed by retrying and must not burn quota.
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        raise RuntimeError("PROVIDER_UNAVAILABLE") from last_error

    def _raise_for_provider_error(self, payload: dict[str, Any]) -> None:
        if "Error Message" in payload:
            raise AlphaVantageProviderError(f"PROVIDER_ERROR:{payload['Error Message']}")
        note = payload.get("Note") or payload.get("Information")
        if note and ("rate" in str(note).lower() or "frequency" in str(note).lower() or "limit" in str(note).lower()):
            raise AlphaVantageProviderError(f"RATE_LIMITED:{note}")
        if note and "premium" in str(note).lower():
            raise AlphaVantageProviderError(f"PREMIUM_ENDPOINT_REQUIRED:{note}")
        if not any(key for key in payload if "Time Series" in key or "Time Series FX" in key):
            raise AlphaVantageProviderError(f"EMPTY_RESPONSE:{json.dumps(payload)[:200]}")

    def _request_params(self, request: HistoricalDataRequest, function: str) -> dict[str, str]:
        params = {"function": function, "outputsize": "full", "datatype": "json"}
        if function == "TIME_SERIES_DAILY":
            params["symbol"] = request.provider_symbol
        elif function == "FX_DAILY":
            base, quote = self._pair_symbols(request.provider_symbol)
            params["from_symbol"] = base
            params["to_symbol"] = quote
        elif function == "DIGITAL_CURRENCY_DAILY":
            base, quote = self._pair_symbols(request.provider_symbol)
            params["symbol"] = base
            params["market"] = quote
        else:
            raise ValueError("UNSUPPORTED_FUNCTION")
        return params

    def _pair_symbols(self, provider_symbol: str) -> tuple[str, str]:
        if "/" not in provider_symbol:
            raise ValueError("PROVIDER_SYMBOL_MUST_BE_PAIR:expected 'BASE/QUOTE'")
        base, quote = provider_symbol.split("/", 1)
        return base.strip().upper(), quote.strip().upper()

    def _handle_existing(
        self,
        request: HistoricalDataRequest,
        csv_path: Path,
        provenance_path: Path,
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
            return self.fetch(
                HistoricalDataRequest(
                    **{**asdict(request), "dataset_version": request.new_version, "force_refresh": False, "new_version": None}
                )
            )
        frame = pd.read_csv(csv_path)
        return self._result(
            request, frame, provenance.get("raw_dataframe_hash"), actual_hash, csv_path, provenance_path, warnings, "SKIPPED_EXISTING"
        )

    def _csv_path(self, request: HistoricalDataRequest) -> Path:
        suffix = "" if request.dataset_version == "v1" else f"_{request.dataset_version}"
        return request.output_directory / f"{request.canonical_symbol}_{request.timeframe}{suffix}.csv"

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

    def _source_warnings(self, request: HistoricalDataRequest) -> set[str]:
        warnings = set(RESEARCH_WARNINGS)
        asset = request.asset_class.lower()
        if asset == "forex":
            warnings.add("FOREX_VOLUME_UNAVAILABLE")
        if asset == "crypto":
            warnings.add("CRYPTO_PROVIDER_COMPOSITE_MARKET_UNSPECIFIED_VENUE")
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
        asset = request.asset_class.lower()
        return {
            "provider": self.code,
            "provider_version": self.version,
            "provider_classification": self.classification,
            "provider_independence": self.provider_independence,
            "provider_symbol": request.provider_symbol,
            "canonical_symbol": request.canonical_symbol,
            "client": self.client_name,
            "client_version": self.client_version,
            "function": self._function(request),
            "requested_start": request.start,
            "requested_end": request.end,
            "received_start": None if frame.empty else str(frame["timestamp"].iloc[0]),
            "received_end": None if frame.empty else str(frame["timestamp"].iloc[-1]),
            "downloaded_at": datetime.now(UTC).isoformat(),
            "split_adjusted": False,
            "dividend_adjusted": False,
            "price_adjustment_basis": "provider_unadjusted_raw" if asset == "equity_etf" else "not_applicable",
            "volume_type": "unavailable" if asset == "forex" else request.volume_type,
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
            interval="daily",
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


def _extract_field(day: dict[str, Any], field: str) -> str | None:
    pattern = FIELD_PATTERNS[field]
    candidates = [key for key in day if pattern.search(key)]
    if not candidates:
        return None
    non_currency_tagged = [key for key in candidates if not NOT_USD_CURRENCY_HINT.search(key)]
    chosen = non_currency_tagged[0] if non_currency_tagged else candidates[0]
    return day[chosen]


def canonicalize_alpha_vantage_payload(payload: dict[str, Any], function: str, asset_class: str) -> pd.DataFrame:
    series_key = next((key for key in payload if "Time Series" in key), None)
    if series_key is None:
        raise ValueError("CANONICALIZATION_FAILED:no_time_series_key")
    series = payload[series_key]
    rows = []
    for date_str, day in series.items():
        open_ = _extract_field(day, "open")
        high_ = _extract_field(day, "high")
        low_ = _extract_field(day, "low")
        close_ = _extract_field(day, "close")
        volume_ = _extract_field(day, "volume") if asset_class.lower() != "forex" else None
        rows.append(
            {
                "timestamp": date_str,
                "open": open_,
                "high": high_,
                "low": low_,
                "close": close_,
                "volume": volume_ if volume_ is not None else 0,
            }
        )
    canonical = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    canonical["timestamp"] = pd.to_datetime(canonical["timestamp"], utc=True, errors="coerce")
    for column in PRICE_COLUMNS:
        canonical[column] = pd.to_numeric(canonical[column], errors="coerce")
    canonical["volume"] = pd.to_numeric(canonical["volume"], errors="coerce").fillna(0)
    canonical = canonical.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    canonical["timestamp"] = canonical["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    return canonical


def canonical_csv_hash(frame: pd.DataFrame) -> str:
    content = frame.to_csv(index=False, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
