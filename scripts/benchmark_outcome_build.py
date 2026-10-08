from __future__ import annotations

import math
import os
import time
from datetime import UTC, datetime, timedelta

from market_genome_domain.database import Base
from market_genome_domain.models import (
    DataSource,
    Instrument,
    OutcomeObservation,
    PriceBar,
    Timeframe,
)
from market_genome_outcomes.service import OutcomeBuildService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def main() -> None:
    bar_count = int(os.environ.get("MARKET_GENOME_OUTCOME_BENCH_BARS", "1000"))
    lengths = [int(part) for part in os.environ.get("MARKET_GENOME_OUTCOME_BENCH_LENGTHS", "8,16,32,64").split(",")]
    horizons = [int(part) for part in os.environ.get("MARKET_GENOME_OUTCOME_BENCH_HORIZONS", "1,3,5,10,20,40,60").split(",")]
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        instrument = Instrument(symbol="OUTBENCH", name="Outcome Benchmark", asset_class="synthetic", exchange="LOCAL")
        timeframe = Timeframe(code="M1", seconds=60, label="1 minute", is_intraday=True)
        source = DataSource(name="outcome-benchmark", source_type="synthetic")
        session.add_all([instrument, timeframe, source])
        session.flush()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        for idx in range(bar_count):
            close = 100.0 + idx * 0.005 + math.sin(idx / 11.0) * 0.7
            session.add(
                PriceBar(
                    instrument_id=instrument.id,
                    timeframe_id=timeframe.id,
                    source_id=source.id,
                    timestamp=start + timedelta(minutes=idx),
                    open=close - 0.03,
                    high=close + 0.3,
                    low=close - 0.3,
                    close=close,
                    volume=1000 + (idx % 100),
                    data_quality_flags=[],
                )
            )
        session.commit()
        started = time.monotonic()
        windows = WindowBuildService(session).build(instrument.id, timeframe.id, lengths, mode="full")
        outcomes = OutcomeBuildService(session).build(
            instrument_id=instrument.id,
            timeframe_id=timeframe.id,
            horizons=horizons,
            mode="full",
        )
        elapsed = round(time.monotonic() - started, 3)
        complete = session.scalar(select(OutcomeObservation).where(OutcomeObservation.is_complete.is_(True)).limit(1)) is not None
        print(
            "benchmark_outcome_build "
            f"backend=sqlite-memory bars={bar_count} lengths={lengths} horizons={horizons} "
            f"windows={windows.created_windows} observations={outcomes.created_observations} "
            f"partial={outcomes.partial_observations} has_complete={complete} "
            f"observations_per_second={round(outcomes.created_observations / max(elapsed, 1e-9), 3)} "
            f"elapsed_seconds={elapsed} batch_size=all"
        )


if __name__ == "__main__":
    main()
