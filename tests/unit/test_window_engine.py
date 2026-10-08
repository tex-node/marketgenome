from datetime import UTC, datetime, timedelta

from market_genome_domain.models import PatternWindow, PriceBar
from market_genome_domain.registry import RegistryService
from market_genome_window_engine.service import (
    WindowBuildService,
    WindowQualityPolicy,
    build_configuration_hash,
    continuity_policy_version,
    expected_window_count,
    source_data_hash,
)
from sqlalchemy.orm import Session


def _seed_bars(db_session: Session, count: int = 10) -> tuple[str, str]:
    registry = RegistryService(db_session)
    instrument = registry.create_instrument("BTCUSDT", exchange="BINANCE")
    timeframe = registry.create_timeframe("H1", 3600, "1 hour")
    source = registry.create_source("TEST")
    start = datetime(2024, 1, 1, tzinfo=UTC)
    for index in range(count):
        db_session.add(
            PriceBar(
                instrument_id=instrument.id,
                timeframe_id=timeframe.id,
                source_id=source.id,
                timestamp=start + timedelta(hours=index),
                open=100 + index,
                high=101 + index,
                low=99 + index,
                close=100.5 + index,
                volume=1000 + index,
                data_quality_flags=[],
            )
        )
    db_session.commit()
    return instrument.id, timeframe.id


def test_expected_window_count_formula() -> None:
    assert expected_window_count(10, 4, 1) == 7
    assert expected_window_count(10, 4, 2) == 4
    assert expected_window_count(3, 4, 1) == 0


def test_window_build_boundaries_and_idempotency(db_session: Session) -> None:
    instrument_id, timeframe_id = _seed_bars(db_session, 10)
    service = WindowBuildService(db_session)

    first = service.build(instrument_id, timeframe_id, window_lengths=[4], stride=1, mode="full")
    second = service.build(instrument_id, timeframe_id, window_lengths=[4], stride=1, mode="full")

    assert first.created_windows == 7
    assert second.created_windows == 0
    assert second.existing_windows == 7


def test_incremental_build_only_adds_future_windows(db_session: Session) -> None:
    instrument_id, timeframe_id = _seed_bars(db_session, 5)
    service = WindowBuildService(db_session)
    first = service.build(instrument_id, timeframe_id, window_lengths=[3], stride=1, mode="incremental")
    old_hashes = [
        window.source_data_hash
        for window in db_session.query(PatternWindow).order_by(PatternWindow.end_timestamp).all()
    ]
    registry = RegistryService(db_session)
    source = registry.get_source_by_name("TEST")
    db_session.add(
        PriceBar(
            instrument_id=instrument_id,
            timeframe_id=timeframe_id,
            source_id=source.id,
            timestamp=datetime(2024, 1, 1, 5, tzinfo=UTC),
            open=105,
            high=106,
            low=104,
            close=105.5,
            volume=1005,
            data_quality_flags=[],
        )
    )
    db_session.commit()
    second = service.build(instrument_id, timeframe_id, window_lengths=[3], stride=1, mode="incremental")

    assert first.created_windows == 3
    assert second.created_windows == 1
    new_hashes = [
        window.source_data_hash
        for window in db_session.query(PatternWindow).order_by(PatternWindow.end_timestamp).limit(3).all()
    ]
    assert new_hashes == old_hashes


def test_hashes_are_deterministic_and_no_lookahead(db_session: Session) -> None:
    _seed_bars(db_session, 5)
    bars = db_session.query(PriceBar).order_by(PriceBar.timestamp).all()
    digest = source_data_hash(bars[:3])
    assert source_data_hash(bars[:3]) == digest
    assert source_data_hash(bars[:4]) != digest
    bars[4].close = 999
    assert source_data_hash(bars[:3]) == digest
    bars[1].close = 999
    assert source_data_hash(bars[:3]) != digest
    assert build_configuration_hash({"b": 2, "a": 1}) == build_configuration_hash({"a": 1, "b": 2})


def test_continuity_policy_version_is_explicit() -> None:
    assert continuity_policy_version(WindowQualityPolicy(calendar_mode="continuous")) == "strict_elapsed_time_v1"
    assert continuity_policy_version(WindowQualityPolicy(calendar_mode="session_based")) == "observed_session_sequence_v1"


def test_continuity_policy_participates_in_window_identity(db_session: Session) -> None:
    instrument_id, timeframe_id = _seed_bars(db_session, 10)
    service = WindowBuildService(db_session)

    continuous = service.build(
        instrument_id,
        timeframe_id,
        window_lengths=[4],
        stride=1,
        mode="full",
        quality_policy=WindowQualityPolicy(calendar_mode="continuous"),
    )
    session_based = service.build(
        instrument_id,
        timeframe_id,
        window_lengths=[4],
        stride=1,
        mode="full",
        quality_policy=WindowQualityPolicy(calendar_mode="session_based"),
    )
    session_based_rerun = service.build(
        instrument_id,
        timeframe_id,
        window_lengths=[4],
        stride=1,
        mode="full",
        quality_policy=WindowQualityPolicy(calendar_mode="session_based"),
    )

    assert continuous.created_windows == 7
    assert session_based.created_windows == 7
    assert session_based_rerun.created_windows == 0
    assert session_based_rerun.existing_windows == 7
    assert continuous.build.configuration["continuity_policy_version"] == "strict_elapsed_time_v1"
    assert session_based.build.configuration["continuity_policy_version"] == "observed_session_sequence_v1"
    assert continuous.build.configuration_hash != session_based.build.configuration_hash
    assert db_session.query(PatternWindow).count() == 14
