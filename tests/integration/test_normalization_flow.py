from pathlib import Path

from fastapi.testclient import TestClient
from market_genome_api.main import app
from market_genome_data_ingestion.csv_import import CsvImportMetadata, persist_csv_import
from market_genome_domain.models import NormalizedPattern, PatternWindow, PriceBar
from market_genome_normalization.service import NormalizationBuildService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy.orm import Session


def _prepare_windows(session: Session) -> tuple[str, str]:
    result = persist_csv_import(
        session,
        Path("tests/fixtures/sample_ohlcv.csv"),
        CsvImportMetadata(
            symbol="SYNTH",
            instrument_name="Synthetic Market",
            asset_class="synthetic",
            exchange="TEST",
            currency="USD",
            timezone="UTC",
            timeframe="H1",
            source_name="SYNTHETIC_CSV",
            timeframe_seconds=3600,
        ),
    )
    WindowBuildService(session).build(result.instrument.id, result.timeframe.id, [8, 16], mode="full")
    return result.instrument.id, result.timeframe.id


def test_normalization_build_idempotency_and_no_lookahead(db_session: Session) -> None:
    instrument_id, timeframe_id = _prepare_windows(db_session)
    service = NormalizationBuildService(db_session)
    first = service.build("anchored_log_return", 16, instrument_id=instrument_id, timeframe_id=timeframe_id, mode="full")
    second = service.build("anchored_log_return", 16, instrument_id=instrument_id, timeframe_id=timeframe_id, mode="incremental")
    pattern = db_session.query(NormalizedPattern).first()
    old_values = pattern.normalized_values
    source = db_session.query(PriceBar).first().source_id
    db_session.add(
        PriceBar(
            instrument_id=instrument_id,
            timeframe_id=timeframe_id,
            source_id=source,
            timestamp=db_session.query(PatternWindow).order_by(PatternWindow.end_timestamp.desc()).first().end_timestamp,
            open=999,
            high=1000,
            low=998,
            close=999,
            volume=1,
            data_quality_flags=[],
        )
    )

    assert first.created_representations == 18
    assert second.created_representations == 0
    assert second.existing_representations == 18
    assert pattern.normalized_values == old_values


def test_normalization_api_flow(api_session: Session) -> None:
    instrument_id, timeframe_id = _prepare_windows(api_session)
    client = TestClient(app)
    response = client.post(
        "/api/v1/normalization/builds",
        json={
            "normalization_method": "range_close",
            "resample_points": 8,
            "mode": "full",
            "instrument_id": instrument_id,
            "timeframe_id": timeframe_id,
            "window_length": 8,
        },
    )
    assert response.status_code == 200
    assert response.json()["created_representations"] == 13
    listed = client.get("/api/v1/normalized-patterns").json()
    values = client.get(f"/api/v1/normalized-patterns/{listed[0]['id']}/values").json()
    diagnostics = client.get(f"/api/v1/normalized-patterns/{listed[0]['id']}/diagnostics").json()
    assert len(values["values"]["close"]) == 8
    assert diagnostics["output_point_count"] == 8

