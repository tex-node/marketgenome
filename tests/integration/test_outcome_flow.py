from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from market_genome_api.main import app
from market_genome_context.service import ContextBuildService
from market_genome_data_ingestion.csv_import import CsvImportMetadata, persist_csv_import
from market_genome_domain.models import (
    MarketContext,
    MarketDNA,
    NormalizedPattern,
    OutcomeObservation,
    PatternWindow,
)
from market_genome_features.service import FeatureBuildService
from market_genome_normalization.service import NormalizationBuildService
from market_genome_outcomes.definitions import OUTCOME_DEFINITION_CODES
from market_genome_outcomes.service import OutcomeBuildService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy.orm import Session


def _prepare_windows(session: Session, symbol: str = "OUTCOME_SYNTH") -> tuple[str, str]:
    result = persist_csv_import(
        session,
        Path("tests/fixtures/sample_ohlcv.csv"),
        CsvImportMetadata(
            symbol=symbol,
            instrument_name="Outcome Synthetic Market",
            asset_class="synthetic",
            exchange="TEST",
            currency="USD",
            timezone="UTC",
            timeframe="H1",
            source_name=f"{symbol}_CSV",
            timeframe_seconds=3600,
        ),
    )
    WindowBuildService(session).build(result.instrument.id, result.timeframe.id, [8], mode="full")
    return result.instrument.id, result.timeframe.id


def test_outcome_build_is_idempotent_and_persists_complete_and_partial_observations(db_session: Session) -> None:
    instrument_id, timeframe_id = _prepare_windows(db_session)
    service = OutcomeBuildService(db_session)

    first = service.build(
        instrument_id=instrument_id,
        timeframe_id=timeframe_id,
        window_length=8,
        horizons=[1, 3, 5, 10],
        mode="full",
    )
    second = service.build(
        instrument_id=instrument_id,
        timeframe_id=timeframe_id,
        window_length=8,
        horizons=[1, 3, 5, 10],
        mode="incremental",
    )
    item = db_session.query(OutcomeObservation).first()

    assert first.created_observations > 0
    assert first.partial_observations > 0
    assert second.created_observations == 0
    assert second.existing_observations == first.created_observations
    assert item.anchor_timestamp == item.window_end_timestamp
    assert item.first_future_timestamp > item.anchor_timestamp
    assert item.scalar_values["future_log_return"] is not None
    assert item.forward_path["values"][0] == 0.0
    assert item.diagnostics["anchor_excluded_from_future"] is True


def test_outcome_source_window_hash_mismatch_is_rejected(db_session: Session) -> None:
    instrument_id, timeframe_id = _prepare_windows(db_session, "OUTCOME_BAD_HASH")
    window = db_session.query(PatternWindow).first()
    window.source_data_hash = "bad"
    db_session.commit()

    result = OutcomeBuildService(db_session).build(
        instrument_id=instrument_id,
        timeframe_id=timeframe_id,
        window_length=8,
        horizons=[1, 3],
        mode="full",
    )

    assert result.failed_observations == 2
    assert "OUTCOME_SOURCE_WINDOW_HASH_MISMATCH" in result.errors


def test_outcome_build_does_not_mutate_feature_or_context_sources(db_session: Session) -> None:
    instrument_id, timeframe_id = _prepare_windows(db_session, "OUTCOME_NO_LEAKAGE")
    NormalizationBuildService(db_session).build(
        "anchored_log_return",
        64,
        instrument_id=instrument_id,
        timeframe_id=timeframe_id,
        window_length=8,
        mode="full",
    )
    FeatureBuildService(db_session).build(instrument_id=instrument_id, timeframe_id=timeframe_id, window_length=8, mode="full")
    ContextBuildService(db_session).build(instrument_id=instrument_id, timeframe_id=timeframe_id, window_length=8, mode="full")
    normalized_hashes = {item.id: item.representation_hash for item in db_session.query(NormalizedPattern)}
    dna_hashes = {item.id: item.feature_vector_hash for item in db_session.query(MarketDNA)}
    context_hashes = {item.id: item.context_hash for item in db_session.query(MarketContext)}

    OutcomeBuildService(db_session).build(
        instrument_id=instrument_id,
        timeframe_id=timeframe_id,
        window_length=8,
        horizons=[1, 3, 5],
        mode="full",
    )

    assert {item.id: item.representation_hash for item in db_session.query(NormalizedPattern)} == normalized_hashes
    assert {item.id: item.feature_vector_hash for item in db_session.query(MarketDNA)} == dna_hashes
    assert {item.id: item.context_hash for item in db_session.query(MarketContext)} == context_hashes


def test_outcome_api_flow(api_session: Session) -> None:
    instrument_id, timeframe_id = _prepare_windows(api_session, "OUTCOME_API")
    client = TestClient(app)

    definitions = client.get("/api/v1/outcomes/definitions")
    assert definitions.status_code == 200
    assert len(definitions.json()) == len(OUTCOME_DEFINITION_CODES)
    assert client.get("/api/v1/outcomes/sets/forward_outcomes_v1").status_code == 200
    build = client.post(
        "/api/v1/outcomes/builds",
        json={
            "outcome_set_code": "forward_outcomes_v1",
            "horizons": [1, 3],
            "mode": "full",
            "instrument_id": instrument_id,
            "timeframe_id": timeframe_id,
            "window_length": 8,
        },
    )
    assert build.status_code == 200
    assert build.json()["created_observations"] > 0
    observations = client.get("/api/v1/outcome-observations").json()
    outcome_id = observations[0]["id"]
    window_id = observations[0]["pattern_window_id"]
    assert client.get(f"/api/v1/outcome-observations/{outcome_id}/values").status_code == 200
    assert client.get(f"/api/v1/outcome-observations/{outcome_id}/path").status_code == 200
    assert client.get(f"/api/v1/outcome-observations/{outcome_id}/barriers").status_code == 200
    assert client.get(f"/api/v1/outcome-observations/{outcome_id}/diagnostics").status_code == 200
    assert client.get(f"/api/v1/windows/{window_id}/outcomes").status_code == 200
