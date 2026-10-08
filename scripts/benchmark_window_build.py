from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from market_genome_domain.database import Base
from market_genome_domain.models import PriceBar
from market_genome_domain.registry import RegistryService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def main() -> None:
    bar_count = 10_000
    lengths = [8, 16, 32, 64]
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as session:
        registry = RegistryService(session)
        instrument = registry.create_instrument("SYNTH", exchange="BENCH")
        timeframe = registry.create_timeframe("M1", 60, "1 minute")
        source = registry.create_source("SYNTHETIC_BENCH")
        start = datetime(2024, 1, 1, tzinfo=UTC)
        session.bulk_save_objects(
            [
                PriceBar(
                    instrument_id=instrument.id,
                    timeframe_id=timeframe.id,
                    source_id=source.id,
                    timestamp=start + timedelta(minutes=index),
                    open=100 + index * 0.01,
                    high=100.5 + index * 0.01,
                    low=99.5 + index * 0.01,
                    close=100.1 + index * 0.01,
                    volume=1000 + index,
                    data_quality_flags=[],
                )
                for index in range(bar_count)
            ]
        )
        session.commit()
        started = time.monotonic()
        result = WindowBuildService(session).build(
            instrument.id,
            timeframe.id,
            window_lengths=lengths,
            stride=1,
            mode="full",
        )
        elapsed = round(time.monotonic() - started, 3)
        print(
            {
                "backend": "sqlite-memory",
                "bar_count": bar_count,
                "window_lengths": lengths,
                "windows_created": result.created_windows,
                "elapsed_seconds": elapsed,
            }
        )


if __name__ == "__main__":
    main()

