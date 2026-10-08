from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from market_genome_api.main import app
from market_genome_context.service import ContextBuildService
from market_genome_domain.models import (
    DataSource,
    Instrument,
    OutcomeObservation,
    PriceBar,
    StudyArm,
    StudyDatasetEntry,
    StudyEpisode,
    Timeframe,
)
from market_genome_features.service import FeatureBuildService
from market_genome_normalization.service import NormalizationBuildService
from market_genome_outcomes.service import OutcomeBuildService
from market_genome_studies.service import MultiAssetStudyService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy.orm import Session


def _add_instrument(session: Session, symbol: str, asset_class: str, offset: float) -> tuple[str, str]:
    instrument = Instrument(symbol=symbol, name=symbol, asset_class=asset_class, exchange="TEST", currency="USD", timezone="UTC")
    timeframe = session.query(Timeframe).filter(Timeframe.code == "D1").first()
    if timeframe is None:
        timeframe = Timeframe(code="D1", seconds=86400, label="1 day", is_intraday=False)
    source = DataSource(name=f"{symbol}_CSV", source_type="synthetic")
    session.add_all([instrument, timeframe, source])
    session.flush()
    start = datetime(2020, 1, 1, tzinfo=UTC)
    for index in range(42):
        close = 100 + offset + index * 0.1
        session.add(
            PriceBar(
                instrument_id=instrument.id,
                timeframe_id=timeframe.id,
                source_id=source.id,
                timestamp=start + timedelta(days=index),
                open=close - 0.1,
                high=close + 0.5,
                low=close - 0.5,
                close=close,
                volume=1000 + index,
                data_quality_flags=[],
            )
        )
    session.commit()
    WindowBuildService(session).build(instrument.id, timeframe.id, [8], mode="full")
    NormalizationBuildService(session).build("anchored_log_return", 64, instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=8, mode="full")
    FeatureBuildService(session).build(instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=8, mode="full")
    ContextBuildService(session).build(instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=8, mode="full")
    OutcomeBuildService(session).build(instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=8, horizons=[1, 3], mode="full")
    return instrument.id, timeframe.id


def _study_config() -> dict:
    instruments = [
        {"symbol": "AAA", "asset_class": "index", "timeframe": "D1", "source": "USER_CSV"},
        {"symbol": "BBB", "asset_class": "commodity", "timeframe": "D1", "source": "USER_CSV"},
        {"symbol": "CCC", "asset_class": "forex", "timeframe": "D1", "source": "USER_CSV"},
    ]
    return {
        "study": {"code": "multi_asset_episode_study_v1", "version": "study_v1", "name": "integration_multi_asset_study"},
        "universe": {"instruments": instruments},
        "data_requirements": {
            "minimum_bars": 30,
            "minimum_unique_episodes": 2,
            "preferred_unique_episodes": 3,
            "maximum_single_episode_share": 0.80,
            "maximum_top_three_episode_share": 1.00,
        },
        "windows": {"lengths": [8]},
        "outcomes": {"horizons": [1, 3]},
        "retrieval": {
            "historical_as_of": True,
            "purge_overlaps": True,
            "maximum_matches_per_episode": [1, 3, None],
            "neighbour_counts": [10],
            "minimum_joint_feature_ratio": 0.2,
        },
        "study_quality_gate": {
            "minimum_instruments_overall": 3,
            "minimum_asset_classes": 3,
            "minimum_eligible_queries_overall": 10,
            "minimum_unique_episodes_overall": 3,
            "minimum_complete_outcome_rate": 0.50,
        },
    }


def _prepare(session: Session) -> None:
    _add_instrument(session, "AAA", "index", 0)
    _add_instrument(session, "BBB", "commodity", 20)
    _add_instrument(session, "CCC", "forex", 40)


def test_multi_asset_study_service_flow_and_final_lock(db_session: Session) -> None:
    _prepare(db_session)
    service = MultiAssetStudyService(db_session)
    study = service.create(_study_config())

    assert db_session.query(StudyDatasetEntry).filter(StudyDatasetEntry.study_id == study.id).count() == 3
    assert db_session.query(StudyEpisode).filter(StudyEpisode.study_id == study.id).count() > 0
    assert service.preflight(study.id).status == "READY_FOR_FORMAL_STUDY"

    service.run_pilot(study.id)
    service.run_validation(study.id)
    locked = service.lock_final_test(study.id)
    lock_hash = locked.final_test_lock_hash
    relocked = service.lock_final_test(study.id)
    final = service.run_final_test(study.id)

    assert lock_hash == relocked.final_test_lock_hash
    assert final.status == "FINAL_TEST_COMPLETE"
    assert db_session.query(StudyArm).filter(StudyArm.study_id == study.id, StudyArm.period_role == "FINAL_TEST").count() > 0
    assert "Multi-Asset Diagnostic Study" in service.report(study.id)
    assert db_session.query(OutcomeObservation).count() > 0


def test_multi_asset_study_api_flow(api_session: Session) -> None:
    _prepare(api_session)
    client = TestClient(app)

    assert client.get("/api/v1/studies/definitions").status_code == 200
    created = client.post("/api/v1/studies", json={"configuration": _study_config()})
    assert created.status_code == 200
    study_id = created.json()["id"]
    assert client.get(f"/api/v1/studies/{study_id}").status_code == 200
    assert client.get(f"/api/v1/studies/{study_id}/datasets").json()
    assert client.get(f"/api/v1/studies/{study_id}/preflight").json()
    assert client.get(f"/api/v1/studies/{study_id}/episodes").json()
    assert client.post(f"/api/v1/studies/{study_id}/run-pilot").status_code == 200
    assert client.post(f"/api/v1/studies/{study_id}/run-validation").status_code == 200
    assert client.post(f"/api/v1/studies/{study_id}/lock-final-test", json={"configuration": {}}).status_code == 200
    assert client.post(f"/api/v1/studies/{study_id}/run-final-test").status_code == 200
    assert client.get(f"/api/v1/studies/{study_id}/arms").json()
    assert client.get(f"/api/v1/studies/{study_id}/metrics").status_code == 200
    assert client.get(f"/api/v1/studies/{study_id}/episode-diversity").status_code == 200
    assert "Multi-Asset Diagnostic Study" in client.get(f"/api/v1/studies/{study_id}/report").json()["report"]
