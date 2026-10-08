from __future__ import annotations

from pathlib import Path

import pandas as pd
from market_genome_data_ingestion.cross_provider_qa import (
    compare_canonical_files,
    compare_price_series,
)


def _canonical(dates: list[str], closes: list[float]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "timestamp": [f"{d}T00:00:00+0000" for d in dates],
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [0] * len(dates),
        }
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["date"] = frame["timestamp"].dt.date
    return frame


def test_compare_price_series_flags_close_agreement_as_ok() -> None:
    dates = [f"2024-01-{d:02d}" for d in range(1, 11)]
    base_closes = [100.0 + i for i in range(10)]
    other_closes = [100.05 + i for i in range(10)]  # near-identical returns, slightly different level

    result = compare_price_series(
        _canonical(dates, base_closes), _canonical(dates, other_closes), base_label="yahoo", other_label="alpha_vantage"
    )

    assert result["matched_timestamps"] == 10
    assert result["quality_flag"] == "OK"
    assert result["close_return_correlation"] > 0.99
    assert result["large_discrepancy_count"] == 0


def test_compare_price_series_flags_wrong_symbol_as_review_required() -> None:
    # Two independent random walks (fixed seed) -- realistic variance, near-zero
    # return correlation, standing in for "wrong symbol / wrong contract" data.
    dates = [f"2024-01-{d:02d}" for d in range(1, 11)]
    base_closes = [100.001, 100.3, 100.026, 99.135, 98.681, 97.689, 97.749, 99.089, 98.597, 97.977]
    unrelated_closes = [50.49, 50.847, 50.952, 50.022, 49.992, 50.688, 49.344, 48.886, 46.985, 45.695]

    result = compare_price_series(
        _canonical(dates, base_closes), _canonical(dates, unrelated_closes), base_label="yahoo", other_label="alpha_vantage"
    )

    assert result["close_return_correlation"] < 0.85
    assert result["quality_flag"] == "REVIEW_REQUIRED"


def test_compare_price_series_reports_missing_timestamps_on_partial_overlap() -> None:
    base = _canonical([f"2024-01-{d:02d}" for d in range(1, 6)], [100.0 + i for i in range(5)])
    other = _canonical([f"2024-01-{d:02d}" for d in range(3, 8)], [100.0 + i for i in range(5)])

    result = compare_price_series(base, other, base_label="yahoo", other_label="alpha_vantage")

    assert result["missing_in_other"] == 2
    assert result["missing_in_base"] == 2
    assert result["matched_timestamps"] == 3


def test_compare_canonical_files_reads_csvs(tmp_path: Path) -> None:
    base = _canonical([f"2024-01-{d:02d}" for d in range(1, 6)], [100.0 + i for i in range(5)])
    other = _canonical([f"2024-01-{d:02d}" for d in range(1, 6)], [100.02 + i for i in range(5)])
    base_path = tmp_path / "base.csv"
    other_path = tmp_path / "other.csv"
    base.drop(columns=["date"]).to_csv(base_path, index=False)
    other.drop(columns=["date"]).to_csv(other_path, index=False)

    result = compare_canonical_files(base_path, other_path, base_label="yahoo", other_label="alpha_vantage")

    assert result["matched_timestamps"] == 5
    assert result["quality_flag"] == "OK"
