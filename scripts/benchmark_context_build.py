from __future__ import annotations

import math
import os
import time
from datetime import UTC, datetime, timedelta

from market_genome_context.service import ContextBuildService
from market_genome_domain.database import Base
from market_genome_domain.models import DataSource, Instrument, MarketContext, PriceBar, Timeframe
from market_genome_features.service import FeatureBuildService
from market_genome_normalization.service import NormalizationBuildService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _run_case(bar_count: int, missing_volume: bool) -> None:
    lengths = [int(part) for part in os.environ.get("MARKET_GENOME_CONTEXT_BENCH_LENGTHS", "8,16,32,64,128,256").split(",")]
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        instrument = Instrument(symbol="CTXBENCH", name="Context Benchmark", asset_class="synthetic", exchange="LOCAL")
        timeframe = Timeframe(code="M1", seconds=60, label="1 minute", is_intraday=True)
        source = DataSource(name=f"context-benchmark-{missing_volume}", source_type="synthetic")
        session.add_all([instrument, timeframe, source])
        session.flush()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        for idx in range(bar_count):
            close = 100.0 + idx * 0.01 + math.sin(idx / 17.0)
            session.add(
                PriceBar(
                    instrument_id=instrument.id,
                    timeframe_id=timeframe.id,
                    source_id=source.id,
                    timestamp=start + timedelta(minutes=idx),
                    open=close - 0.05,
                    high=close + 0.25,
                    low=close - 0.25,
                    close=close,
                    volume=0 if missing_volume else 1000 + (idx % 50),
                    data_quality_flags=[],
                )
            )
        session.commit()
        started = time.monotonic()
        WindowBuildService(session).build(instrument.id, timeframe.id, lengths, mode="full")
        NormalizationBuildService(session).build("anchored_log_return", 64, instrument_id=instrument.id, timeframe_id=timeframe.id, mode="full")
        FeatureBuildService(session).build(instrument_id=instrument.id, timeframe_id=timeframe.id, mode="full")
        context = ContextBuildService(session).build(instrument_id=instrument.id, timeframe_id=timeframe.id, mode="full")
        elapsed = round(time.monotonic() - started, 3)
        rows = list(session.scalars(select(MarketContext)))
        avg = lambda values: round(sum(values) / len(values), 6) if values else 0.0
        print(
            "benchmark_context_build "
            f"backend=sqlite-memory bars={bar_count} lengths={lengths} missing_volume={missing_volume} "
            f"source_market_dna={context.source_market_dna_count} contexts={context.created_contexts} "
            f"partial={context.partial_contexts} avg_completeness={avg([float(r.completeness_score) for r in rows])} "
            f"avg_dimension_confidence={avg([float(r.composite_confidence) for r in rows])} "
            f"avg_composite_confidence={avg([float(r.composite_confidence) for r in rows])} "
            f"contexts_per_second={round(context.created_contexts / max(elapsed, 1e-9), 3)} "
            f"elapsed_seconds={elapsed} batch_size=all"
        )


def main() -> None:
    bar_count = int(os.environ.get("MARKET_GENOME_CONTEXT_BENCH_BARS", "1000"))
    _run_case(bar_count, missing_volume=False)
    _run_case(bar_count, missing_volume=True)


if __name__ == "__main__":
    main()
