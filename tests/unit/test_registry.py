from market_genome_domain.registry import RegistryService
from sqlalchemy.orm import Session


def test_instrument_resolution_is_idempotent(db_session: Session) -> None:
    service = RegistryService(db_session)
    first = service.create_instrument(symbol="BTCUSDT", exchange="BINANCE")
    second = service.create_instrument(symbol="BTCUSDT", exchange="BINANCE")

    assert first.id == second.id


def test_seed_standard_timeframes_is_idempotent(db_session: Session) -> None:
    service = RegistryService(db_session)
    first = service.seed_standard_timeframes()
    second = service.seed_standard_timeframes()

    assert len(first) == 9
    assert len(second) == 9
    assert len(service.list_timeframes()) == 9
    assert service.get_timeframe_by_code("MN1").seconds is None

