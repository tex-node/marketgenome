from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class HistoricalDataRequest:
    provider_symbol: str
    canonical_symbol: str
    instrument_name: str
    asset_class: str
    exchange: str
    currency: str
    timezone: str
    timeframe: str
    start: str
    end: str
    auto_adjust: bool
    include_actions: bool
    volume_type: str
    price_adjustment_basis: str
    output_directory: Path
    dataset_version: str = "v1"
    delay_seconds: float = 2.0
    maximum_retries: int = 3
    initial_retry_delay: float = 2.0
    backoff_multiplier: float = 2.0
    maximum_retry_delay: float = 30.0
    force_refresh: bool = False
    new_version: str | None = None


@dataclass(frozen=True)
class HistoricalDataResult:
    provider_code: str
    provider_version: str
    client_name: str
    client_version: str
    provider_symbol: str
    canonical_symbol: str
    requested_start: str
    requested_end: str
    received_start: str | None
    received_end: str | None
    interval: str
    row_count: int
    raw_dataframe_hash: str | None
    canonical_csv_hash: str | None
    csv_path: str | None
    provenance_path: str | None
    warnings: list[str] = field(default_factory=list)
    status: str = "PENDING"

    def as_dict(self) -> dict[str, object]:
        return {
            "provider_code": self.provider_code,
            "provider_version": self.provider_version,
            "client_name": self.client_name,
            "client_version": self.client_version,
            "provider_symbol": self.provider_symbol,
            "canonical_symbol": self.canonical_symbol,
            "requested_start": self.requested_start,
            "requested_end": self.requested_end,
            "received_start": self.received_start,
            "received_end": self.received_end,
            "interval": self.interval,
            "row_count": self.row_count,
            "raw_dataframe_hash": self.raw_dataframe_hash,
            "canonical_csv_hash": self.canonical_csv_hash,
            "csv_path": self.csv_path,
            "provenance_path": self.provenance_path,
            "warnings": self.warnings,
            "status": self.status,
        }


class HistoricalDataProvider(Protocol):
    code: str
    version: str

    def fetch(self, request: HistoricalDataRequest) -> HistoricalDataResult:
        ...


def list_providers() -> list[dict[str, str]]:
    return [
        {
            "code": "yahoo_finance_v1",
            "version": "provider_v1",
            "classification": "PILOT_AND_RESEARCH_SOURCE",
            "client": "yfinance",
            "provider_independence": "NOT_INDEPENDENT",
        },
        {
            "code": "alpha_vantage_v1",
            "version": "provider_v1",
            "classification": "INDEPENDENT_PUBLIC_MARKET_DATA_PROVIDER",
            "client": "alpha_vantage_http",
            "provider_independence": "CONFIRMED",
        },
    ]


def get_provider(code: str) -> HistoricalDataProvider:
    if code == "yahoo_finance_v1":
        from market_genome_data_ingestion.providers.yahoo_finance import YahooFinanceProvider

        return YahooFinanceProvider()
    if code == "alpha_vantage_v1":
        from market_genome_data_ingestion.providers.alpha_vantage import AlphaVantageProvider

        return AlphaVantageProvider()
    raise ValueError("DATA_PROVIDER_NOT_FOUND")
