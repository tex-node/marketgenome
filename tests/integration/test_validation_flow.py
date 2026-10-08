from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from market_genome_api.main import app
from market_genome_context.service import ContextBuildService
from market_genome_data_ingestion.csv_import import CsvImportMetadata, persist_csv_import
from market_genome_domain.models import (
    ExperimentArtifact,
    ExperimentFold,
    ExperimentMetric,
    QueryEvaluation,
)
from market_genome_features.service import FeatureBuildService
from market_genome_normalization.service import NormalizationBuildService
from market_genome_outcomes.service import OutcomeBuildService
from market_genome_validation.service import ValidationExperimentService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy.orm import Session


def _prepare_validation_inputs(session: Session, symbol: str = "VALIDATION_SYNTH") -> tuple[str, str]:
    result = persist_csv_import(
        session,
        Path("tests/fixtures/sample_ohlcv.csv"),
        CsvImportMetadata(
            symbol=symbol,
            instrument_name="Validation Synthetic Market",
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
    OutcomeBuildService(session).build(
        instrument_id=result.instrument.id,
        timeframe_id=result.timeframe.id,
        window_length=8,
        horizons=[1],
        mode="full",
    )
    return result.instrument.id, result.timeframe.id


def _small_experiment_config(instrument_id: str, timeframe_id: str, *, run_nonce: str) -> dict:
    return {
        "name": f"Validation smoke {run_nonce}",
        "instrument_ids": [instrument_id],
        "timeframe_ids": [timeframe_id],
        "window_lengths": [8],
        "outcome_horizons": [1],
        "validation": {"minimum_index_windows": 6, "test_window_count": 2, "fold_count": 1, "embargo_bars": 0},
        "neighbour_counts": [2],
        "baseline_methods": ["random_history_v1", "unconditional_outcome_v1"],
        "weighting_method": "uniform_v1",
        "purge_source_overlap": True,
        "purge_outcome_overlap": True,
        "run_nonce": run_nonce,
    }


def test_validation_experiment_persists_run_folds_evaluations_metrics_and_report(db_session: Session) -> None:
    instrument_id, timeframe_id = _prepare_validation_inputs(db_session)

    result = ValidationExperimentService(db_session).run(_small_experiment_config(instrument_id, timeframe_id, run_nonce="service"))

    assert result.errors == []
    assert result.folds == 1
    assert result.query_evaluations > 0
    assert result.metric_records > 0
    assert result.artifact_records == 1
    assert result.run.decision in {"INSUFFICIENT_DATA", "NO_SUPPORTED_EDGE", "PROMISING", "OUT_OF_SAMPLE_SUPPORTED"}
    assert db_session.query(ExperimentFold).filter(ExperimentFold.experiment_run_id == result.run.id).count() == 1
    assert db_session.query(QueryEvaluation).filter(QueryEvaluation.experiment_run_id == result.run.id).count() == result.query_evaluations
    assert db_session.query(ExperimentMetric).filter(ExperimentMetric.experiment_run_id == result.run.id).count() == result.metric_records
    artifact = db_session.query(ExperimentArtifact).filter(ExperimentArtifact.experiment_run_id == result.run.id).one()
    assert artifact.artifact_type == "markdown_report"

    evaluation = db_session.query(QueryEvaluation).filter(QueryEvaluation.experiment_run_id == result.run.id, QueryEvaluation.similarity_method.is_not(None)).first()
    assert evaluation is not None
    assert evaluation.retrieval_diagnostics["historical_as_of"] is True
    assert evaluation.retrieval_diagnostics["uses_query_actual_outcome_for_forecast"] is False


def test_validation_api_flow(api_session: Session) -> None:
    instrument_id, timeframe_id = _prepare_validation_inputs(api_session, "VALIDATION_API")
    client = TestClient(app)

    assert client.get("/api/v1/experiments/definitions").status_code == 200
    assert client.get("/api/v1/validation/methods").status_code == 200
    assert client.get("/api/v1/validation/baselines").status_code == 200
    assert client.get("/api/v1/validation/metrics").status_code == 200
    assert client.get("/api/v1/validation/weighting").status_code == 200

    created = client.post(
        "/api/v1/experiments/runs",
        json={"configuration": _small_experiment_config(instrument_id, timeframe_id, run_nonce="api")},
    )
    assert created.status_code == 200
    run_id = created.json()["id"]
    assert client.get(f"/api/v1/experiments/runs/{run_id}").status_code == 200
    assert client.get(f"/api/v1/experiments/runs/{run_id}/folds").json()
    assert client.get(f"/api/v1/experiments/runs/{run_id}/evaluations").json()
    assert client.get(f"/api/v1/experiments/runs/{run_id}/metrics").json()
    report = client.get(f"/api/v1/experiments/runs/{run_id}/report")
    assert report.status_code == 200
    assert "Experiment Report" in report.json()["report"]
