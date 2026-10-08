from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from market_genome_domain.database import Base
from market_genome_domain.models import PriceBar
from market_genome_domain.registry import RegistryService
from market_genome_normalization.service import NormalizationBuildService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def main() -> None:
    bar_count = 10_000
    lengths = [8, 16, 32, 64]
    points = 64
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
        windows = WindowBuildService(session).build(instrument.id, timeframe.id, lengths, mode="full")
        started = time.monotonic()
        close_result = NormalizationBuildService(session).build(
            "anchored_log_return",
            points,
            instrument_id=instrument.id,
            timeframe_id=timeframe.id,
            mode="full",
        )
        close_elapsed = round(time.monotonic() - started, 3)
        started = time.monotonic()
        ohlc_result = NormalizationBuildService(session).build(
            "anchored_ohlc",
            points,
            instrument_id=instrument.id,
            timeframe_id=timeframe.id,
            mode="full",
        )
        ohlc_elapsed = round(time.monotonic() - started, 3)
        print(
            {
                "backend": "sqlite-memory",
                "source_bars": bar_count,
                "source_windows": windows.created_windows,
                "window_lengths": lengths,
                "close_method": "anchored_log_return",
                "close_representations": close_result.created_representations,
                "close_elapsed_seconds": close_elapsed,
                "close_representations_per_second": round(close_result.created_representations / close_elapsed, 2),
                "ohlc_method": "anchored_ohlc",
                "ohlc_representations": ohlc_result.created_representations,
                "ohlc_elapsed_seconds": ohlc_elapsed,
                "ohlc_representations_per_second": round(ohlc_result.created_representations / ohlc_elapsed, 2),
                "resample_points": points,
                "batch_size": "session transaction",
            }
        )


if __name__ == "__main__":
    main()

