from pathlib import Path

from market_genome_data_ingestion.csv_import import validate_ohlcv_csv


def test_valid_csv_is_accepted(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2024-01-01T00:00:00Z,100,105,99,102,1000\n"
        "2024-01-01T00:01:00Z,102,106,101,104,900\n",
        encoding="utf-8",
    )

    frame, report = validate_ohlcv_csv(csv_path)

    assert len(frame) == 2
    assert report.rows_seen == 2
    assert report.rows_valid == 2
    assert report.rows_rejected == 0
    assert report.source_hash


def test_invalid_ohlc_row_is_rejected(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2024-01-01T00:00:00Z,100,99,98,102,1000\n",
        encoding="utf-8",
    )

    frame, report = validate_ohlcv_csv(csv_path)

    assert frame.empty
    assert report.rows_rejected == 1
    assert any(issue.code == "invalid_high" for issue in report.errors)


def test_duplicate_timestamp_is_rejected(tmp_path: Path) -> None:
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2024-01-01T00:00:00Z,100,105,99,102,1000\n"
        "2024-01-01T00:00:00Z,102,106,101,104,900\n",
        encoding="utf-8",
    )

    frame, report = validate_ohlcv_csv(csv_path)

    assert len(frame) == 1
    assert report.rows_rejected == 1
    assert any(issue.code == "duplicate_timestamp" for issue in report.errors)

