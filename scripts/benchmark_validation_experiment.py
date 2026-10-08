from __future__ import annotations

import math
import os
import time
from datetime import UTC, datetime, timedelta

from market_genome_context.service import ContextBuildService
from market_genome_domain.database import Base
from market_genome_domain.models import (
    DataSource,
    ExperimentArtifact,
    ExperimentFold,
    ExperimentMetric,
    Instrument,
    PriceBar,
    QueryEvaluation,
    Timeframe,
)
from market_genome_features.service import FeatureBuildService
from market_genome_normalization.service import NormalizationBuildService
from market_genome_outcomes.service import OutcomeBuildService
from market_genome_validation.service import ValidationExperimentService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def main() -> None:
    bar_count = int(os.environ.get("MARKET_GENOME_VALIDATION_BENCH_BARS", "150"))
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        instrument = Instrument(symbol="VALBENCH", name="Validation Benchmark", asset_class="synthetic", exchange="LOCAL")
        timeframe = Timeframe(code="M1", seconds=60, label="1 minute", is_intraday=True)
        source = DataSource(name="validation-benchmark", source_type="synthetic")
        session.add_all([instrument, timeframe, source])
        session.flush()
        start = datetime(2024, 1, 1, tzinfo=UTC)
        for idx in range(bar_count):
            close = 100.0 + idx * 0.005 + math.sin(idx / 11.0) * 0.7 + math.sin(idx / 29.0) * 0.3
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
                    volume=1000 + idx % 40,
                    data_quality_flags=[],
                )
            )
        session.commit()

        started = time.monotonic()
        WindowBuildService(session).build(instrument.id, timeframe.id, [8], mode="full")
        NormalizationBuildService(session).build("anchored_log_return", 64, instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=8, mode="full")
        FeatureBuildService(session).build(instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=8, mode="full")
        ContextBuildService(session).build(instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=8, mode="full")
        OutcomeBuildService(session).build(instrument_id=instrument.id, timeframe_id=timeframe.id, window_length=8, horizons=[1, 3], mode="full")
        result = ValidationExperimentService(session).run(
            {
                "name": "Validation benchmark",
                "instrument_ids": [instrument.id],
                "timeframe_ids": [timeframe.id],
                "window_lengths": [8],
                "outcome_horizons": [1, 3],
                "validation": {"minimum_index_windows": 40, "test_window_count": 10, "fold_count": 2, "embargo_bars": 1},
                "neighbour_counts": [5],
                "baseline_methods": ["random_history_v1", "unconditional_outcome_v1", "recent_mean_return_v1"],
                "run_nonce": "benchmark",
            }
        )
        elapsed = round(time.monotonic() - started, 3)
        print(
            "benchmark_validation_experiment "
            f"backend=sqlite-memory bars={bar_count} folds={session.query(ExperimentFold).count()} "
            f"evaluations={session.query(QueryEvaluation).count()} metrics={session.query(ExperimentMetric).count()} "
            f"artifacts={session.query(ExperimentArtifact).count()} decision={result.decision} "
            f"evaluations_per_second={round(result.query_evaluations / max(elapsed, 1e-9), 3)} elapsed_seconds={elapsed}"
        )


if __name__ == "__main__":
    main()
