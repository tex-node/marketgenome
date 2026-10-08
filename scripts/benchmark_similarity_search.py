from __future__ import annotations

import math
import os
import time
from datetime import UTC, datetime, timedelta

from market_genome_context.service import ContextBuildService
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
from market_genome_similarity.service import SimilaritySearchService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def main() -> None:
    bar_count = int(os.environ.get("MARKET_GENOME_SIMILARITY_BENCH_BARS", "300"))
    top_k = int(os.environ.get("MARKET_GENOME_SIMILARITY_BENCH_TOP_K", "20"))
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        instrument = Instrument(symbol="SIMBENCH", name="Similarity Benchmark", asset_class="synthetic", exchange="LOCAL")
        timeframe = Timeframe(code="M1", seconds=60, label="1 minute", is_intraday=True)
        source = DataSource(name="similarity-benchmark", source_type="synthetic")
        session.add_all([instrument, timeframe, source])
        session.flush()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        for idx in range(bar_count):
            close = 100.0 + idx * 0.01 + math.sin(idx / 13.0)
            session.add(
                PriceBar(
                    instrument_id=instrument.id,
                    timeframe_id=timeframe.id,
                    source_id=source.id,
                    timestamp=start + timedelta(minutes=idx),
                    open=close - 0.02,
                    high=close + 0.25,
                    low=close - 0.25,
                    close=close,
                    volume=1000 + idx % 50,
                    data_quality_flags=[],
                )
            )
        session.commit()
        started = time.monotonic()
        WindowBuildService(session).build(instrument.id, timeframe.id, [8], mode="full")
        NormalizationBuildService(session).build("anchored_log_return", 64, instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=8, mode="full")
        FeatureBuildService(session).build(instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=8, mode="full")
        ContextBuildService(session).build(instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=8, mode="full")
        query_window = session.query(PatternWindow).order_by(PatternWindow.end_timestamp.desc()).first()
        result = SimilaritySearchService(session).search(query_window.id, top_k=top_k)
        elapsed = round(time.monotonic() - started, 3)
        match_count = session.query(SimilarityMatch).filter(SimilarityMatch.query_id == result.query.id).count()
        print(
            "benchmark_similarity_search "
            f"backend=sqlite-memory bars={bar_count} top_k={top_k} "
            f"candidates={result.candidate_count} matches={match_count} "
            f"matches_per_second={round(match_count / max(elapsed, 1e-9), 3)} elapsed_seconds={elapsed}"
        )


if __name__ == "__main__":
    main()
