from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from market_genome_api.main import app
from market_genome_context.service import ContextBuildService
from market_genome_data_ingestion.csv_import import CsvImportMetadata, persist_csv_import
from market_genome_diagnostics.service import RetrievalDiagnosticService
from market_genome_domain.models import DiagnosticArtifact, PatternWindow, SimilarityMatch
from market_genome_features.service import FeatureBuildService
from market_genome_normalization.service import NormalizationBuildService
from market_genome_outcomes.service import OutcomeBuildService
from market_genome_similarity.service import SimilaritySearchService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy.orm import Session


def _prepare_inputs(session: Session, symbol: str = "DIAG_SYNTH") -> tuple[str, str]:
    result = persist_csv_import(
        session,
        Path("tests/fixtures/sample_ohlcv.csv"),
        CsvImportMetadata(
            symbol=symbol,
            instrument_name="Diagnostic Synthetic Market",
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
    NormalizationBuildService(session).build(
        "anchored_log_return",
        64,
        instrument_id=result.instrument.id,
        timeframe_id=result.timeframe.id,
        window_length=8,
        mode="full",
    )
    FeatureBuildService(session).build(instrument_id=result.instrument.id, timeframe_id=result.timeframe.id, window_length=8, mode="full")
    ContextBuildService(session).build(instrument_id=result.instrument.id, timeframe_id=result.timeframe.id, window_length=8, mode="full")
    OutcomeBuildService(session).build(instrument_id=result.instrument.id, timeframe_id=result.timeframe.id, window_length=8, horizons=[1], mode="full")
    return result.instrument.id, result.timeframe.id


def _config(instrument_id: str, timeframe_id: str, run_nonce: str) -> dict:
    return {
        "diagnostic_code": "representation_quality_diagnostic_v1",
        "name": f"Diagnostic smoke {run_nonce}",
        "instrument_ids": [instrument_id],
        "timeframe_ids": [timeframe_id],
        "window_lengths": [8],
        "outcome_horizons": [1],
        "similarity_methods": ["dna_robust_cosine_v1", "shape_dna_context_v2"],
        "scaling_methods": ["robust_median_mad_v1"],
        "availability_policy": "joint_available_with_coverage_penalty_v1",
        "minimum_joint_feature_ratio": 0.2,
        "maximum_records": 50,
        "maximum_pairs": 100,
        "run_nonce": run_nonce,
    }


def test_retrieval_diagnostic_service_persists_artifacts_and_refined_similarity_works(db_session: Session) -> None:
    instrument_id, timeframe_id = _prepare_inputs(db_session)

    run = RetrievalDiagnosticService(db_session).run(_config(instrument_id, timeframe_id, "service"))
    artifacts = db_session.query(DiagnosticArtifact).filter(DiagnosticArtifact.experiment_run_id == run.id).all()
    query_window = db_session.query(PatternWindow).order_by(PatternWindow.end_timestamp.desc()).first()
    result = SimilaritySearchService(db_session).search(query_window.id, similarity_method_code="shape_dna_context_v2", top_k=3)
    matches = db_session.query(SimilarityMatch).filter(SimilarityMatch.query_id == result.query.id).all()

    assert run.status == "COMPLETED"
    assert run.decision in {"INSUFFICIENT_SAMPLE", "NO_RETRIEVAL_EDGE", "REFINEMENT_PROMISING", "REPRESENTATION_FAILURE", "EPISODE_CONCENTRATION_FAILURE"}
    assert {"FEATURE_DISTRIBUTION", "CORRELATION_MATRIX", "DISTANCE_OUTCOME_CURVE", "EPISODE_CONCENTRATION", "WINDOW_HORIZON_MATRIX", "DIAGNOSTIC_REPORT"} <= {artifact.artifact_type for artifact in artifacts}
    assert matches
    assert "joint_feature_ratio" in matches[0].component_scores
    assert matches[0].diagnostics["uses_future_outcomes"] is False


def test_retrieval_diagnostic_api_flow(api_session: Session) -> None:
    instrument_id, timeframe_id = _prepare_inputs(api_session, "DIAG_API")
    client = TestClient(app)

    assert client.get("/api/v1/diagnostics/definitions").status_code == 200
    assert client.get("/api/v1/diagnostics/scaling-methods").status_code == 200
    assert client.get("/api/v1/diagnostics/availability-policies").status_code == 200
    assert client.get("/api/v1/diagnostics/weight-configurations").status_code == 200
    assert any(item["code"] == "shape_dna_context_v2" for item in client.get("/api/v1/similarity/methods").json())

    created = client.post("/api/v1/diagnostics/experiments", json={"configuration": _config(instrument_id, timeframe_id, "api")})
    assert created.status_code == 200
    run_id = created.json()["id"]
    assert client.get(f"/api/v1/diagnostics/experiments/{run_id}").status_code == 200
    assert client.get(f"/api/v1/diagnostics/experiments/{run_id}/feature-distributions").json()["features"]
    assert client.get(f"/api/v1/diagnostics/experiments/{run_id}/redundancy").status_code == 200
    assert client.get(f"/api/v1/diagnostics/experiments/{run_id}/distance-outcome").status_code == 200
    assert client.get(f"/api/v1/diagnostics/experiments/{run_id}/episode-concentration").status_code == 200
    assert client.get(f"/api/v1/diagnostics/experiments/{run_id}/window-horizon").status_code == 200
    report = client.get(f"/api/v1/diagnostics/experiments/{run_id}/report")
    assert report.status_code == 200
    assert "Retrieval Diagnostic Report" in report.json()["report"]
