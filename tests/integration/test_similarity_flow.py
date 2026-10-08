from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from market_genome_api.main import app
from market_genome_context.service import ContextBuildService
from market_genome_data_ingestion.csv_import import CsvImportMetadata, persist_csv_import
from market_genome_domain.models import PatternWindow, SimilarityMatch
from market_genome_features.service import FeatureBuildService
from market_genome_normalization.service import NormalizationBuildService
from market_genome_similarity.service import SimilaritySearchService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy.orm import Session


def _prepare_similarity_inputs(session: Session, symbol: str = "SIM_SYNTH") -> str:
    result = persist_csv_import(
        session,
        Path("tests/fixtures/sample_ohlcv.csv"),
        CsvImportMetadata(
            symbol=symbol,
            instrument_name="Similarity Synthetic Market",
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
    return result.instrument.id


def test_similarity_search_persists_historical_matches_and_excludes_self(db_session: Session) -> None:
    _prepare_similarity_inputs(db_session)
    query_window = db_session.query(PatternWindow).order_by(PatternWindow.end_timestamp.desc()).first()

    result = SimilaritySearchService(db_session).search(query_window.id, top_k=5)
    matches = db_session.query(SimilarityMatch).filter(SimilarityMatch.query_id == result.query.id).all()

    assert result.returned_match_count == 5
    assert len(matches) == 5
    assert all(match.candidate_window_id != query_window.id for match in matches)
    assert all(match.diagnostics["uses_future_outcomes"] is False for match in matches)
    candidate_windows = {match.candidate_window_id: db_session.get(PatternWindow, match.candidate_window_id) for match in matches}
    assert all(window.end_timestamp < query_window.end_timestamp for window in candidate_windows.values())
    assert [match.rank for match in matches] == [1, 2, 3, 4, 5]


def test_similarity_query_window_without_history_returns_no_matches(db_session: Session) -> None:
    _prepare_similarity_inputs(db_session, "SIM_NO_HISTORY")
    query_window = db_session.query(PatternWindow).order_by(PatternWindow.end_timestamp).first()

    result = SimilaritySearchService(db_session).search(query_window.id, top_k=5)

    assert result.candidate_count == 0
    assert result.returned_match_count == 0


def test_similarity_api_flow(api_session: Session) -> None:
    _prepare_similarity_inputs(api_session, "SIM_API")
    query_window = api_session.query(PatternWindow).order_by(PatternWindow.end_timestamp.desc()).first()
    client = TestClient(app)

    methods = client.get("/api/v1/similarity/methods")
    assert methods.status_code == 200
    assert any(item["code"] == "market_analogue_v1" for item in methods.json())
    search = client.post(
        "/api/v1/similarity/search",
        json={"query_window_id": query_window.id, "similarity_method_code": "market_analogue_v1", "top_k": 3},
    )
    assert search.status_code == 200
    query_id = search.json()["id"]
    assert search.json()["returned_match_count"] == 3
    assert client.get(f"/api/v1/similarity/queries/{query_id}").status_code == 200
    matches = client.get(f"/api/v1/similarity/queries/{query_id}/matches")
    assert matches.status_code == 200
    assert len(matches.json()) == 3
    similar = client.get(f"/api/v1/windows/{query_window.id}/similar?top_k=2")
    assert similar.status_code == 200
    assert len(similar.json()) == 2
