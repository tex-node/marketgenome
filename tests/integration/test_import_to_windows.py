from pathlib import Path

from market_genome_data_ingestion.csv_import import CsvImportMetadata, persist_csv_import
from market_genome_domain.models import PatternWindow
from market_genome_window_engine.service import WindowBuildService, list_window_bars
from sqlalchemy.orm import Session


def test_csv_import_to_window_build_flow(db_session: Session) -> None:
    result = persist_csv_import(
        db_session,
        Path("tests/fixtures/sample_ohlcv.csv"),
        CsvImportMetadata(
            symbol="BTCUSDT",
            instrument_name="Bitcoin / Tether",
            asset_class="crypto",
            exchange="BINANCE",
            currency="USDT",
            timezone="UTC",
            timeframe="H1",
            source_name="BINANCE_CSV",
            timeframe_seconds=3600,
        ),
    )

    build = WindowBuildService(db_session).build(
        result.instrument.id,
        result.timeframe.id,
        window_lengths=[8, 16],
        stride=1,
        mode="full",
    )
    window = db_session.query(PatternWindow).filter_by(window_length=8).order_by(PatternWindow.end_timestamp).first()
    bars = list_window_bars(db_session, window)

    assert result.data_import.rows_inserted == 20
    assert build.created_windows == 18
    assert len(bars) == 8
    assert bars[0].timestamp == window.start_timestamp
    assert bars[-1].timestamp == window.end_timestamp

