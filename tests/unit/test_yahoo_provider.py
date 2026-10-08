from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from market_genome_data_ingestion.acquisition import (
    acquisition_plan,
    fetch_manifest,
    load_provider_manifest,
    provider_catalog,
    requests_from_manifest,
)
from market_genome_data_ingestion.providers import get_provider
from market_genome_data_ingestion.providers.base import HistoricalDataRequest
from market_genome_data_ingestion.providers.yahoo_finance import (
    YahooFinanceProvider,
    canonical_csv_hash,
    canonicalize_yahoo_frame,
)
from market_genome_studies.service import MultiAssetStudyService
from sqlalchemy.orm import Session


def _frame(volume: bool = True, multi: bool = False) -> pd.DataFrame:
    data = {
        "Open": [100.0, 101.0, 102.0],
        "High": [101.0, 102.0, 103.0],
        "Low": [99.0, 100.0, 101.0],
        "Close": [100.5, 101.5, 102.5],
    }
    if volume:
        data["Volume"] = [1000, 1100, 1200]
    frame = pd.DataFrame(data, index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]))
    frame.index.name = "Date"
    if multi:
        frame.columns = pd.MultiIndex.from_product([frame.columns, ["SPY"]])
    return frame


def _request(tmp_path: Path, **overrides) -> HistoricalDataRequest:
    values = {
        "provider_symbol": "SPY",
        "canonical_symbol": "SPY",
        "instrument_name": "SPDR S&P 500 ETF Trust",
        "asset_class": "equity_etf",
        "exchange": "ARCA",
        "currency": "USD",
        "timezone": "America/New_York",
        "timeframe": "D1",
        "start": "2024-01-01",
        "end": "2024-01-10",
        "auto_adjust": True,
        "include_actions": True,
        "volume_type": "exchange_volume",
        "price_adjustment_basis": "provider_auto_adjusted",
        "output_directory": tmp_path,
        "delay_seconds": 0,
        "maximum_retries": 0,
    }
    values.update(overrides)
    return HistoricalDataRequest(**values)


def _manifest(tmp_path: Path) -> dict:
    return {
        "manifest": {"code": "yahoo_unit", "version": "provider_manifest_v1"},
        "provider": {"code": "yahoo_finance_v1"},
        "acquisition": {
            "start": "2024-01-01",
            "end": "2024-01-10",
            "interval": "1d",
            "delay_seconds": 0,
            "retries": 0,
            "auto_adjust": True,
            "actions": True,
        },
        "instruments": [
            {
                "provider_symbol": "SPY",
                "canonical_symbol": "SPY",
                "name": "SPY",
                "asset_class": "equity_etf",
                "exchange": "ARCA",
                "currency": "USD",
                "timezone": "America/New_York",
                "timeframe": "D1",
                "volume_type": "exchange_volume",
                "enabled": True,
            },
            {
                "provider_symbol": "DISABLED",
                "canonical_symbol": "DISABLED",
                "name": "Disabled",
                "asset_class": "equity_etf",
                "exchange": "ARCA",
                "currency": "USD",
                "timezone": "UTC",
                "timeframe": "D1",
                "volume_type": "exchange_volume",
                "enabled": False,
            },
        ],
        "_manifest_path": str(tmp_path / "manifest.yaml"),
    }


def test_provider_registry() -> None:
    assert any(provider["code"] == "yahoo_finance_v1" for provider in provider_catalog())
    assert get_provider("yahoo_finance_v1").code == "yahoo_finance_v1"
    with pytest.raises(ValueError, match="DATA_PROVIDER_NOT_FOUND"):
        get_provider("missing")


def test_yahoo_canonicalization_standard_multiindex_and_missing_volume() -> None:
    standard = canonicalize_yahoo_frame(_frame())
    multi = canonicalize_yahoo_frame(_frame(multi=True))
    missing_volume = canonicalize_yahoo_frame(_frame(volume=False))

    assert list(standard.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert canonical_csv_hash(standard) == canonical_csv_hash(multi)
    assert (missing_volume["volume"] == 0).all()


def test_yahoo_canonicalization_repairs_adjusted_ohlc_bounds() -> None:
    frame = _frame()
    frame.loc[frame.index[0], "High"] = 100.0
    frame.loc[frame.index[1], "Low"] = 102.0

    canonical = canonicalize_yahoo_frame(frame)

    assert canonical.loc[0, "high"] == canonical.loc[0, ["open", "high", "low", "close"]].max()
    assert canonical.loc[1, "low"] == canonical.loc[1, ["open", "high", "low", "close"]].min()


def test_yahoo_fetch_writes_provenance_and_skips_existing(tmp_path: Path) -> None:
    provider = YahooFinanceProvider(downloader=lambda *args, **kwargs: _frame())
    request = _request(tmp_path)

    result = provider.fetch(request)
    skipped = provider.fetch(request)
    provenance = json.loads(Path(result.provenance_path).read_text(encoding="utf-8"))

    assert result.status == "COMPLETED"
    assert skipped.status == "SKIPPED_EXISTING"
    assert provenance["provider"] == "yahoo_finance_v1"
    assert provenance["client"] == "yfinance"
    assert provenance["auto_adjust"] is True
    assert "POSTGRES_PASSWORD" not in json.dumps(provenance)


def test_immutable_hash_mismatch_and_new_version(tmp_path: Path) -> None:
    provider = YahooFinanceProvider(downloader=lambda *args, **kwargs: _frame())
    request = _request(tmp_path)
    result = provider.fetch(request)
    Path(result.csv_path).write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="IMMUTABLE_ACQUISITION_HASH_MISMATCH"):
        provider.fetch(request)

    revised = YahooFinanceProvider(downloader=lambda *args, **kwargs: _frame()).fetch(
        _request(tmp_path, dataset_version="v2")
    )
    assert revised.csv_path.endswith("SPY_D1_v2.csv")


def test_empty_invalid_duplicate_and_non_positive_responses(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="EMPTY_RESPONSE"):
        YahooFinanceProvider(downloader=lambda *args, **kwargs: pd.DataFrame()).fetch(_request(tmp_path))

    duplicate = _frame()
    duplicate.index = pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-03"])
    duplicate.index.name = "Date"
    with pytest.raises(ValueError, match="DUPLICATE_TIMESTAMPS"):
        YahooFinanceProvider(downloader=lambda *args, **kwargs: duplicate).fetch(_request(tmp_path / "dup"))

    bad = _frame()
    bad["Open"] = [-1.0, 101.0, 102.0]
    with pytest.raises(ValueError, match="NON_POSITIVE_PRICES"):
        YahooFinanceProvider(downloader=lambda *args, **kwargs: bad).fetch(_request(tmp_path / "bad"))


def test_manifest_validation_filtering_dry_run_and_fetch(tmp_path: Path) -> None:
    path = tmp_path / "manifest.yaml"
    payload = _manifest(tmp_path)
    path.write_text(json.dumps({key: value for key, value in payload.items() if not key.startswith("_")}), encoding="utf-8")
    loaded = load_provider_manifest(path)

    requests = requests_from_manifest(loaded, symbol="SPY", output_directory=tmp_path)
    plan = acquisition_plan(loaded, symbol="SPY", output_directory=tmp_path)

    assert len(requests) == 1
    assert len(plan) == 1
    assert plan[0]["status"] == "DRY_RUN"

    bad = {**payload, "acquisition": {**payload["acquisition"], "interval": "1h"}}
    bad_path = tmp_path / "bad.yaml"
    bad_path.write_text(json.dumps({key: value for key, value in bad.items() if not key.startswith("_")}), encoding="utf-8")
    with pytest.raises(ValueError, match="UNSUPPORTED_INTERVAL"):
        load_provider_manifest(bad_path)


def test_fetch_manifest_classifies_provider_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest(tmp_path)

    class FailingProvider:
        code = "yahoo_finance_v1"
        version = "provider_v1"

        def fetch(self, request):
            raise ValueError("EMPTY_RESPONSE")

    monkeypatch.setattr("market_genome_data_ingestion.acquisition.get_provider", lambda code: FailingProvider())
    result = fetch_manifest(manifest, output_directory=tmp_path)

    assert result[0]["status"] == "EMPTY_RESPONSE"


def test_yahoo_study_is_pilot_only_and_blocks_final_lock(db_session: Session) -> None:
    cfg = {
        "study": {"code": "multi_asset_episode_study_v1", "version": "study_v1", "name": "yahoo", "classification": "PILOT_ONLY"},
        "provider": {"code": "yahoo_finance_v1"},
        "data_manifest_code": "yahoo_market_data_pilot_v1",
        "runtime_requirements": {"require_postgres": False, "require_real_data": False},
        "universe": {"instruments": []},
        "study_quality_gate": {
            "minimum_instruments_overall": 0,
            "minimum_asset_classes": 0,
            "minimum_eligible_queries_overall": 0,
            "minimum_unique_episodes_overall": 0,
            "minimum_complete_outcome_rate": 0,
        },
    }
    service = MultiAssetStudyService(db_session)
    study = service.create(cfg)
    result = service.preflight(study.id)

    assert result.status == "STUDY_NOT_READY"
    assert "YAHOO_SOURCE_REQUIRES_INDEPENDENT_REPLICATION" in result.blockers
    with pytest.raises(ValueError, match="STUDY_NOT_READY_FOR_FINAL_TEST_LOCK"):
        service.lock_final_test(study.id)
