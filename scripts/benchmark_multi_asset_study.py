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
    PriceBar,
    StudyArm,
    StudyEpisode,
    Timeframe,
)
from market_genome_features.service import FeatureBuildService
from market_genome_normalization.service import NormalizationBuildService
from market_genome_outcomes.service import OutcomeBuildService
from market_genome_studies.service import MultiAssetStudyService
from market_genome_window_engine.service import WindowBuildService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _instrument(session, symbol: str, asset_class: str, offset: float, bars: int) -> None:
    instrument = Instrument(symbol=symbol, name=symbol, asset_class=asset_class, exchange="LOCAL", currency="USD", timezone="UTC")
    timeframe = session.query(Timeframe).filter(Timeframe.code == "D1").first()
    if timeframe is None:
        timeframe = Timeframe(code="D1", seconds=86400, label="1 day", is_intraday=False)
    source = DataSource(name=f"{symbol}-synthetic", source_type="synthetic")
    session.add_all([instrument, timeframe, source])
    session.flush()
    start = datetime(2020, 1, 1, tzinfo=UTC)
    for index in range(bars):
        close = 100 + offset + index * 0.02 + math.sin(index / 11.0) * 0.8
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
                volume=1000 + index % 100,
                data_quality_flags=[],
            )
        )
    session.commit()
    WindowBuildService(session).build(instrument.id, timeframe.id, [16, 32, 64], mode="full")
    NormalizationBuildService(session).build("anchored_log_return", 64, instrument_id=instrument.id, timeframe_id=timeframe.id, mode="full")
    FeatureBuildService(session).build(instrument_id=instrument.id, timeframe_id=timeframe.id, mode="full")
    ContextBuildService(session).build(instrument_id=instrument.id, timeframe_id=timeframe.id, mode="full")
    OutcomeBuildService(session).build(instrument_id=instrument.id, timeframe_id=timeframe.id, horizons=[5, 10, 20], mode="full")


def main() -> None:
    instruments = int(os.environ.get("MARKET_GENOME_STUDY_BENCH_INSTRUMENTS", "4"))
    bars = int(os.environ.get("MARKET_GENOME_STUDY_BENCH_BARS", "90"))
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    started = time.monotonic()
    with session_factory() as session:
        assets = ["index", "commodity", "forex", "crypto", "index", "commodity"]
        for idx in range(instruments):
            _instrument(session, f"BENCH{idx}", assets[idx % len(assets)], idx * 20.0, bars)
        cfg = {
            "study": {"code": "multi_asset_episode_study_v1", "version": "study_v1", "name": "benchmark_multi_asset_study"},
            "universe": {
                "instruments": [
                    {"symbol": f"BENCH{idx}", "asset_class": assets[idx % len(assets)], "timeframe": "D1", "source": "synthetic"}
                    for idx in range(instruments)
                ]
            },
            "data_requirements": {
                "minimum_bars": min(60, bars),
                "minimum_unique_episodes": 2,
                "preferred_unique_episodes": 3,
                "maximum_single_episode_share": 0.80,
                "maximum_top_three_episode_share": 1.00,
            },
            "windows": {"lengths": [16, 32, 64]},
            "outcomes": {"horizons": [5, 10, 20]},
            "retrieval": {
                "historical_as_of": True,
                "purge_overlaps": True,
                "maximum_matches_per_episode": [1, 3],
                "neighbour_counts": [10, 20],
                "minimum_joint_feature_ratio": 0.2,
            },
            "study_quality_gate": {
                "minimum_instruments_overall": min(4, instruments),
                "minimum_asset_classes": min(3, instruments),
                "minimum_eligible_queries_overall": 10,
                "minimum_unique_episodes_overall": 4,
                "minimum_complete_outcome_rate": 0.50,
            },
        }
        service = MultiAssetStudyService(session)
        study = service.create(cfg)
        service.run_pilot(study.id)
        service.run_validation(study.id)
        service.lock_final_test(study.id)
        service.run_final_test(study.id)
        elapsed = time.monotonic() - started
        episode_count = session.query(StudyEpisode).filter(StudyEpisode.study_id == study.id).count()
        arm_count = session.query(StudyArm).filter(StudyArm.study_id == study.id).count()
        print(
            "benchmark_multi_asset_study "
            f"backend=sqlite-memory instruments={instruments} bars_per_instrument={bars} "
            f"episodes={episode_count} study_arms={arm_count} status={study.status} "
            f"decision={study.decision} elapsed_seconds={elapsed:.3f}"
        )


if __name__ == "__main__":
    main()
