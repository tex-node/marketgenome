from __future__ import annotations

import json
from pathlib import Path

import pytest
from market_genome_data_ingestion.acquisition import (
    classify_provider_error,
    validate_provider_manifest,
)
from market_genome_data_ingestion.providers import get_provider
from market_genome_data_ingestion.providers.alpha_vantage import (
    AlphaVantageProvider,
    canonicalize_alpha_vantage_payload,
)
from market_genome_data_ingestion.providers.base import HistoricalDataRequest


def _request(tmp_path: Path, **overrides) -> HistoricalDataRequest:
    values = {
        "provider_symbol": "SPY",
        "canonical_symbol": "SPY_AV",
        "instrument_name": "SPDR S&P 500 ETF Trust",
        "asset_class": "equity_etf",
        "exchange": "ARCA_ALPHA_VANTAGE",
        "currency": "USD",
        "timezone": "America/New_York",
        "timeframe": "D1",
        "start": "2024-01-01",
        "end": "2024-01-10",
        "auto_adjust": False,
        "include_actions": False,
        "volume_type": "exchange_volume",
        "price_adjustment_basis": "provider_unadjusted_raw",
        "output_directory": tmp_path,
        "delay_seconds": 0,
        "maximum_retries": 0,
    }
    values.update(overrides)
    return HistoricalDataRequest(**values)


def _equity_payload() -> dict:
    return {
        "Meta Data": {"2. Symbol": "SPY"},
        "Time Series (Daily)": {
            "2024-01-03": {"1. open": "102.0", "2. high": "103.0", "3. low": "101.0", "4. close": "102.5", "5. volume": "1200"},
            "2024-01-01": {"1. open": "100.0", "2. high": "101.0", "3. low": "99.0", "4. close": "100.5", "5. volume": "1000"},
            "2024-01-02": {"1. open": "101.0", "2. high": "102.0", "3. low": "100.0", "4. close": "101.5", "5. volume": "1100"},
        },
    }


def _fx_payload() -> dict:
    return {
        "Meta Data": {"2. From Symbol": "EUR", "3. To Symbol": "USD"},
        "Time Series FX (Daily)": {
            "2024-01-01": {"1. open": "1.10", "2. high": "1.11", "3. low": "1.09", "4. close": "1.105"},
            "2024-01-02": {"1. open": "1.105", "2. high": "1.12", "3. low": "1.10", "4. close": "1.11"},
        },
    }


def _crypto_payload() -> dict:
    return {
        "Meta Data": {"2. Digital Currency Code": "BTC", "4. Market Code": "USD"},
        "Time Series (Digital Currency Daily)": {
            "2024-01-01": {"1a. open (USD)": "40000.0", "2a. high (USD)": "41000.0", "3a. low (USD)": "39000.0", "4a. close (USD)": "40500.0", "5. volume": "1234.5"},
            "2024-01-02": {"1a. open (USD)": "40500.0", "2a. high (USD)": "42000.0", "3a. low (USD)": "40000.0", "4a. close (USD)": "41500.0", "5. volume": "2345.6"},
        },
    }


def test_provider_registry_includes_alpha_vantage_as_independent() -> None:
    provider = get_provider("alpha_vantage_v1")
    assert provider.code == "alpha_vantage_v1"
    assert provider.provider_independence == "CONFIRMED"


def test_canonicalize_equity_forex_and_crypto_payloads() -> None:
    equity = canonicalize_alpha_vantage_payload(_equity_payload(), "TIME_SERIES_DAILY", "equity_etf")
    fx = canonicalize_alpha_vantage_payload(_fx_payload(), "FX_DAILY", "forex")
    crypto = canonicalize_alpha_vantage_payload(_crypto_payload(), "DIGITAL_CURRENCY_DAILY", "crypto")

    assert list(equity.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert equity["timestamp"].is_monotonic_increasing
    assert equity.loc[0, "open"] == 100.0
    assert (fx["volume"] == 0).all()
    assert crypto.loc[0, "open"] == 40000.0
    assert crypto.loc[0, "volume"] == 1234.5


def test_commodity_asset_class_is_rejected_not_silently_substituted(tmp_path: Path) -> None:
    provider = AlphaVantageProvider(fetcher=lambda params: _equity_payload())
    request = _request(tmp_path, asset_class="commodity_future_proxy", provider_symbol="GC", canonical_symbol="GOLD_FUTURES_AV")

    with pytest.raises(ValueError, match="UNSUPPORTED_ASSET_CLASS_ALPHA_VANTAGE_NO_DAILY_OHLC"):
        provider.fetch(request)


def test_forex_provider_symbol_must_be_a_pair(tmp_path: Path) -> None:
    provider = AlphaVantageProvider(fetcher=lambda params: _fx_payload())
    request = _request(tmp_path, asset_class="forex", provider_symbol="EURUSD", canonical_symbol="EURUSD_AV")

    with pytest.raises(ValueError, match="PROVIDER_SYMBOL_MUST_BE_PAIR"):
        provider.fetch(request)


def test_fetch_writes_provenance_with_unadjusted_basis_and_skips_existing(tmp_path: Path) -> None:
    provider = AlphaVantageProvider(fetcher=lambda params: _equity_payload())
    request = _request(tmp_path)

    result = provider.fetch(request)
    skipped = provider.fetch(request)
    provenance = json.loads(Path(result.provenance_path).read_text(encoding="utf-8"))

    assert result.status == "COMPLETED"
    assert skipped.status == "SKIPPED_EXISTING"
    assert provenance["provider"] == "alpha_vantage_v1"
    assert provenance["provider_independence"] == "CONFIRMED"
    assert provenance["price_adjustment_basis"] == "provider_unadjusted_raw"
    assert provenance["split_adjusted"] is False
    assert "PROVIDER_DATA_RESEARCH_ONLY" in provenance["warnings"]


def test_forex_provenance_flags_volume_unavailable(tmp_path: Path) -> None:
    provider = AlphaVantageProvider(fetcher=lambda params: _fx_payload())
    request = _request(tmp_path, asset_class="forex", provider_symbol="EUR/USD", canonical_symbol="EURUSD_AV")

    result = provider.fetch(request)
    provenance = json.loads(Path(result.provenance_path).read_text(encoding="utf-8"))

    assert "FOREX_VOLUME_UNAVAILABLE" in provenance["warnings"]
    assert provenance["volume_type"] == "unavailable"


def test_crypto_provenance_flags_composite_venue(tmp_path: Path) -> None:
    provider = AlphaVantageProvider(fetcher=lambda params: _crypto_payload())
    request = _request(tmp_path, asset_class="crypto", provider_symbol="BTC/USD", canonical_symbol="BTCUSD_AV")

    result = provider.fetch(request)
    provenance = json.loads(Path(result.provenance_path).read_text(encoding="utf-8"))

    assert "CRYPTO_PROVIDER_COMPOSITE_MARKET_UNSPECIFIED_VENUE" in provenance["warnings"]


def test_immutable_acquisition_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    provider = AlphaVantageProvider(fetcher=lambda params: _equity_payload())
    request = _request(tmp_path)
    result = provider.fetch(request)
    Path(result.csv_path).write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="IMMUTABLE_ACQUISITION_HASH_MISMATCH"):
        provider.fetch(request)


def test_rate_limit_and_premium_responses_are_classified_distinctly(tmp_path: Path) -> None:
    rate_limited = AlphaVantageProvider(fetcher=lambda params: {"Note": "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day."})
    with pytest.raises(Exception, match="RATE_LIMITED"):
        rate_limited.fetch(_request(tmp_path / "a"))

    premium = AlphaVantageProvider(fetcher=lambda params: {"Information": "This is a premium endpoint."})
    with pytest.raises(Exception, match="PREMIUM_ENDPOINT_REQUIRED"):
        premium.fetch(_request(tmp_path / "b"))

    assert classify_provider_error(RuntimeError("RATE_LIMITED:x")) == "PROVIDER_RATE_LIMITED"
    assert classify_provider_error(RuntimeError("PREMIUM_ENDPOINT_REQUIRED:x")) == "PROVIDER_ENDPOINT_REQUIRES_PREMIUM"
    assert classify_provider_error(RuntimeError("ALPHA_VANTAGE_API_KEY_NOT_CONFIGURED")) == "PROVIDER_API_KEY_NOT_CONFIGURED"


def test_manifest_validation_accepts_both_supported_providers() -> None:
    validate_provider_manifest(
        {"provider": {"code": "alpha_vantage_v1"}, "acquisition": {"interval": "1d", "start": "2020-01-01", "end": "2021-01-01"}, "instruments": [{"a": 1}]}
    )
    validate_provider_manifest(
        {"provider": {"code": "yahoo_finance_v1"}, "acquisition": {"interval": "1d", "start": "2020-01-01", "end": "2021-01-01"}, "instruments": [{"a": 1}]}
    )
    with pytest.raises(ValueError, match="UNSUPPORTED_PROVIDER"):
        validate_provider_manifest(
            {"provider": {"code": "stooq_v1"}, "acquisition": {"interval": "1d", "start": "2020-01-01", "end": "2021-01-01"}, "instruments": [{"a": 1}]}
        )
