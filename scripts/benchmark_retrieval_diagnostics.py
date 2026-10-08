from __future__ import annotations

import math
import os
import time
from datetime import UTC, datetime, timedelta

from market_genome_context.service import ContextBuildService
from market_genome_diagnostics.service import RetrievalDiagnosticService
from market_genome_domain.database import Base
from market_genome_domain.models import (
    DataSource,
    Instrument,
    PatternWindow,
    PriceBar,
    SimilarityMatch,
    Timeframe,
)
from market_genome_features.service import FeatureBuildService
from market_genome_normalization.service import NormalizationBuildService
from market_genome_outcomes.service import OutcomeBuildService
from market_genome_similarity.service import SimilaritySearchService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _add_bars(session, instrument: Instrument, timeframe: Timeframe, source: DataSource, bar_count: int, motif: bool) -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    for idx in range(bar_count):
        motif_component = 0.0
        if motif and idx % 50 in {10, 11, 12, 13, 14, 15}:
            motif_component = (idx % 50 - 10) * 0.08
        close = 100.0 + idx * 0.004 + math.sin(idx / 9.0) * 0.6 + motif_component
        session.add(
            PriceBar(
                instrument_id=instrument.id,
                timeframe_id=timeframe.id,
                source_id=source.id,
                timestamp=start + timedelta(minutes=idx),
                open=close - 0.01,
                high=close + 0.2,
                low=close - 0.2,
                close=close,
                volume=1000 + idx % 30,
                data_quality_flags=[],
            )
        )


def _run_case(label: str, motif: bool, bar_count: int) -> tuple[str, float]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    started = time.monotonic()
    with session_factory() as session:
        instrument = Instrument(symbol=f"DIAG{label}", name=f"Diagnostic {label}", asset_class="synthetic", exchange="LOCAL")
        timeframe = Timeframe(code="M1", seconds=60, label="1 minute", is_intraday=True)
        source = DataSource(name=f"diagnostic-{label}", source_type="synthetic")
        session.add_all([instrument, timeframe, source])
        session.flush()
        _add_bars(session, instrument, timeframe, source, bar_count, motif)
        session.commit()
        stage = time.monotonic()
        WindowBuildService(session).build(instrument.id, timeframe.id, [16, 32, 64], mode="full")
        NormalizationBuildService(session).build("anchored_log_return", 64, instrument_id=instrument.id, timeframe_id=timeframe.id, mode="full")
        FeatureBuildService(session).build(instrument_id=instrument.id, timeframe_id=timeframe.id, mode="full")
        ContextBuildService(session).build(instrument_id=instrument.id, timeframe_id=timeframe.id, mode="full")
        OutcomeBuildService(session).build(instrument_id=instrument.id, timeframe_id=timeframe.id, horizons=[5, 10, 20], mode="full")
        feature_time = time.monotonic() - stage
        diag_started = time.monotonic()
        run = RetrievalDiagnosticService(session).run(
            {
                "name": f"Retrieval diagnostics benchmark {label}",
                "instrument_ids": [instrument.id],
                "timeframe_ids": [timeframe.id],
                "window_lengths": [16, 32, 64],
                "outcome_horizons": [5, 10, 20],
                "similarity_methods": ["dna_robust_cosine_v1", "dna_group_balanced_v1", "shape_dna_context_v2"],
                "scaling_methods": ["robust_median_mad_v1"],
                "minimum_joint_feature_ratio": 0.2,
                "maximum_records": 250,
                "maximum_pairs": 1000,
                "run_nonce": label,
            }
        )
        diagnostic_time = time.monotonic() - diag_started
        query_window = session.query(PatternWindow).order_by(PatternWindow.end_timestamp.desc()).first()
        search_started = time.monotonic()
        query = SimilaritySearchService(session).search(query_window.id, similarity_method_code="shape_dna_context_v2", top_k=20)
        search_time = time.monotonic() - search_started
        match_count = session.query(SimilarityMatch).filter(SimilarityMatch.query_id == query.query.id).count()
        elapsed = time.monotonic() - started
        line = (
            f"benchmark_retrieval_diagnostics case={label} backend=sqlite-memory bars={bar_count} "
            f"feature_pipeline_seconds={feature_time:.3f} diagnostic_seconds={diagnostic_time:.3f} "
            f"similarity_search_seconds={search_time:.3f} total_elapsed_seconds={elapsed:.3f} "
            f"candidate_count={query.candidate_count} query_count=1 match_count={match_count} "
            f"diagnostic_decision={run.decision}"
        )
        return line, elapsed


def main() -> None:
    bar_count = int(os.environ.get("MARKET_GENOME_DIAGNOSTIC_BENCH_BARS", "250"))
    for label, motif in (("motif", True), ("noise", False)):
        line, _ = _run_case(label, motif, bar_count)
        print(line)


if __name__ == "__main__":
    main()
