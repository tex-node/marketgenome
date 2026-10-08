from pathlib import Path

from fastapi.testclient import TestClient
from market_genome_api.main import app
from market_genome_context.service import ContextBuildService
from market_genome_data_ingestion.csv_import import CsvImportMetadata, persist_csv_import
from market_genome_domain.models import MarketContext, MarketDNA
from market_genome_features.service import FeatureBuildService
from market_genome_normalization.service import NormalizationBuildService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy.orm import Session


def _prepare_context_inputs(session: Session) -> tuple[str, str]:
    result = persist_csv_import(
        session,
        Path("tests/fixtures/sample_ohlcv.csv"),
        CsvImportMetadata(
            symbol="CONTEXT_SYNTH",
            instrument_name="Context Synthetic Market",
            asset_class="synthetic",
            exchange="TEST",
            currency="USD",
            timezone="UTC",
            timeframe="H1",
            source_name="CONTEXT_SYNTHETIC_CSV",
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
    FeatureBuildService(session).build(instrument_id=result.instrument.id, timeframe_id=result.timeframe.id, window_length=16, mode="full")
    return result.instrument.id, result.timeframe.id


def test_context_build_idempotency_and_partial_multi_resolution(db_session: Session) -> None:
    instrument_id, timeframe_id = _prepare_context_inputs(db_session)
    service = ContextBuildService(db_session)

    first = service.build(instrument_id=instrument_id, timeframe_id=timeframe_id, window_length=16, mode="full")
    second = service.build(instrument_id=instrument_id, timeframe_id=timeframe_id, window_length=16, mode="incremental")
    context = db_session.query(MarketContext).first()

    assert first.created_contexts == first.source_market_dna_count
    assert second.created_contexts == 0
    assert second.existing_contexts == first.source_market_dna_count
    assert context.multi_resolution_state == "UNAVAILABLE"
    assert "PARTIAL_CONTEXT" in context.quality_flags
    assert context.composite_context_code
    assert context.context_hash


def test_context_feature_hash_mismatch_is_rejected(db_session: Session) -> None:
    instrument_id, timeframe_id = _prepare_context_inputs(db_session)
    item = db_session.query(MarketDNA).first()
    item.feature_vector_hash = "bad"
    db_session.commit()

    result = ContextBuildService(db_session).build(instrument_id=instrument_id, timeframe_id=timeframe_id, window_length=16, mode="full")

    assert result.failed_contexts == 1
    assert result.created_contexts == result.source_market_dna_count - 1
    assert "CONTEXT_SOURCE_FEATURE_HASH_MISMATCH" in result.errors


def test_context_api_flow(api_session: Session) -> None:
    instrument_id, timeframe_id = _prepare_context_inputs(api_session)
    client = TestClient(app)

    assert client.get("/api/v1/context/producers").status_code == 200
    assert client.get("/api/v1/context/dimensions").status_code == 200
    build = client.post(
        "/api/v1/context/builds",
        json={
            "context_producer_code": "transparent_context_v1",
            "feature_set_code": "market_dna_v1",
            "mode": "full",
            "instrument_id": instrument_id,
            "timeframe_id": timeframe_id,
            "window_length": 16,
        },
    )
    assert build.status_code == 200
    assert build.json()["created_contexts"] > 0
    listed = client.get("/api/v1/market-contexts").json()
    context_id = listed[0]["id"]
    assert client.get(f"/api/v1/market-contexts/{context_id}/dimensions").status_code == 200
    assert client.get(f"/api/v1/market-contexts/{context_id}/explanation").status_code == 200
    assert client.get(f"/api/v1/market-contexts/{context_id}/diagnostics").status_code == 200
    assert client.get(f"/api/v1/market-contexts/{context_id}/multi-resolution").status_code == 200
