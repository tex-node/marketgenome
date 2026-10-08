from pathlib import Path

from fastapi.testclient import TestClient
from market_genome_api.main import app
from market_genome_data_ingestion.csv_import import CsvImportMetadata, persist_csv_import
from market_genome_domain.models import MarketDNA
from market_genome_features.definitions import MARKET_DNA_V1_FEATURES
from market_genome_features.service import FeatureBuildService
from market_genome_normalization.service import NormalizationBuildService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy.orm import Session


def _prepare_normalized(session: Session) -> tuple[str, str]:
    result = persist_csv_import(
        session,
        Path("tests/fixtures/sample_ohlcv.csv"),
        CsvImportMetadata(
            symbol="FEATURE_SYNTH",
            instrument_name="Feature Synthetic Market",
            asset_class="synthetic",
            exchange="TEST",
            currency="USD",
            timezone="UTC",
            timeframe="H1",
            source_name="FEATURE_SYNTHETIC_CSV",
            timeframe_seconds=3600,
        ),
    )
    WindowBuildService(session).build(result.instrument.id, result.timeframe.id, [16], mode="full")
    NormalizationBuildService(session).build(
        "anchored_log_return",
        64,
        instrument_id=result.instrument.id,
        timeframe_id=result.timeframe.id,
        window_length=16,
        mode="full",
    )
    return result.instrument.id, result.timeframe.id


def test_feature_build_is_idempotent_and_persists_market_dna(db_session: Session) -> None:
    instrument_id, timeframe_id = _prepare_normalized(db_session)
    service = FeatureBuildService(db_session)

    first = service.build(instrument_id=instrument_id, timeframe_id=timeframe_id, window_length=16, mode="full")
    second = service.build(instrument_id=instrument_id, timeframe_id=timeframe_id, window_length=16, mode="incremental")
    item = db_session.query(MarketDNA).first()

    assert first.created_features == first.source_pattern_count
    assert second.created_features == 0
    assert second.existing_features == first.source_pattern_count
    assert item.feature_count == len(MARKET_DNA_V1_FEATURES)
    assert item.available_feature_count > 0
    assert item.diagnostics["source_window_hash_verified"] is True
    assert item.diagnostics["source_representation_hash_verified"] is True


def test_feature_api_flow(api_session: Session) -> None:
    instrument_id, timeframe_id = _prepare_normalized(api_session)
    client = TestClient(app)

    definitions = client.get("/api/v1/features/definitions")
    assert definitions.status_code == 200
    assert len(definitions.json()) == len(MARKET_DNA_V1_FEATURES)
    set_detail = client.get("/api/v1/features/sets/market_dna_v1")
    assert set_detail.status_code == 200
    build = client.post(
        "/api/v1/features/builds",
        json={
            "feature_set_code": "market_dna_v1",
            "mode": "full",
            "instrument_id": instrument_id,
            "timeframe_id": timeframe_id,
            "window_length": 16,
        },
    )
    assert build.status_code == 200
    assert build.json()["created_features"] > 0
    listed = client.get("/api/v1/market-dna").json()
    values = client.get(f"/api/v1/market-dna/{listed[0]['id']}/values").json()
    diagnostics = client.get(f"/api/v1/market-dna/{listed[0]['id']}/diagnostics").json()
    assert len(values["ordered_features"]) == len(MARKET_DNA_V1_FEATURES)
    assert diagnostics["feature_set_code"] == "market_dna_v1"
