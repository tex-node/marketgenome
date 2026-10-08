from __future__ import annotations

import math
import os
import time
from datetime import UTC, datetime, timedelta

from market_genome_domain.database import Base
from market_genome_domain.models import DataSource, Instrument, PriceBar, Timeframe
from market_genome_features.service import FeatureBuildService
from market_genome_normalization.service import NormalizationBuildService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def main() -> None:
    bar_count = int(os.environ.get("MARKET_GENOME_BENCH_BARS", "10000"))
    lengths = [int(part) for part in os.environ.get("MARKET_GENOME_BENCH_LENGTHS", "8,16,32,64").split(",")]
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        instrument = Instrument(symbol="BENCH", name="Benchmark", asset_class="synthetic", exchange="LOCAL")
        timeframe = Timeframe(code="M1", seconds=60, label="1 minute", is_intraday=True)
        source = DataSource(name="benchmark", source_type="synthetic")
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
                    volume=1000 + (idx % 50),
                    data_quality_flags=[],
                )
            )
        session.commit()
        started = time.monotonic()
        windows = WindowBuildService(session).build(instrument.id, timeframe.id, lengths, mode="full")
        normalized = NormalizationBuildService(session).build(
            "anchored_log_return",
            64,
            instrument_id=instrument.id,
            timeframe_id=timeframe.id,
            mode="full",
        )
        features = FeatureBuildService(session).build(
            instrument_id=instrument.id,
            timeframe_id=timeframe.id,
            mode="full",
        )
        elapsed = round(time.monotonic() - started, 3)
        print(
            "benchmark_feature_build "
            f"bars={bar_count} lengths={lengths} "
            f"windows={windows.created_windows} normalized={normalized.created_representations} "
            f"features={features.created_features} elapsed_seconds={elapsed}"
        )


if __name__ == "__main__":
    main()
