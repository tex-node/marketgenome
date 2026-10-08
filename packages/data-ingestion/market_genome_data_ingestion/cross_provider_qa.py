from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

LARGE_RETURN_DISCREPANCY_THRESHOLD = 0.02


def load_canonical_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["date"] = frame["timestamp"].dt.date
    return frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def compare_price_series(
    base: pd.DataFrame,
    other: pd.DataFrame,
    *,
    base_label: str,
    other_label: str,
    large_discrepancy_threshold: float = LARGE_RETURN_DISCREPANCY_THRESHOLD,
) -> dict[str, Any]:
    """Descriptive cross-provider QA, not a model evaluation.

    Detects wrong symbol / wrong contract / bad adjustment / bad timezone / corrupted
    data by comparing overlapping daily close-to-close returns between two independently
    sourced canonical OHLCV series. Does not require identical prices -- legitimate
    providers may disagree slightly on levels (adjustment policy, snapshot timing).
    """
    merged = base[["date", "close"]].merge(
        other[["date", "close"]], on="date", how="outer", suffixes=(f"_{base_label}", f"_{other_label}")
    )
    matched = merged.dropna()
    missing_in_other = merged[merged[f"close_{other_label}"].isna() & merged[f"close_{base_label}"].notna()]
    missing_in_base = merged[merged[f"close_{base_label}"].isna() & merged[f"close_{other_label}"].notna()]

    if len(matched) < 2:
        return {
            "base_label": base_label,
            "other_label": other_label,
            "matched_timestamps": len(matched),
            "missing_in_other": len(missing_in_other),
            "missing_in_base": len(missing_in_base),
            "quality_flag": "INSUFFICIENT_OVERLAP",
        }

    matched = matched.sort_values("date")
    base_close = matched[f"close_{base_label}"].to_numpy(dtype=float)
    other_close = matched[f"close_{other_label}"].to_numpy(dtype=float)
    base_returns = np.diff(base_close) / base_close[:-1]
    other_returns = np.diff(other_close) / other_close[:-1]
    return_difference = np.abs(base_returns - other_returns)
    scale_ratio = other_close / base_close
    correlation = float(np.corrcoef(base_returns, other_returns)[0, 1]) if len(base_returns) > 1 else None

    return {
        "base_label": base_label,
        "other_label": other_label,
        "matched_timestamps": len(matched),
        "missing_in_other": len(missing_in_other),
        "missing_in_base": len(missing_in_base),
        "close_return_correlation": correlation,
        "median_absolute_return_difference": float(np.median(return_difference)),
        "p95_absolute_return_difference": float(np.quantile(return_difference, 0.95)),
        "price_scale_ratio_median": float(np.median(scale_ratio)),
        "price_scale_ratio_min": float(np.min(scale_ratio)),
        "price_scale_ratio_max": float(np.max(scale_ratio)),
        "large_discrepancy_threshold": large_discrepancy_threshold,
        "large_discrepancy_count": int(np.sum(return_difference > large_discrepancy_threshold)),
        "quality_flag": "REVIEW_REQUIRED" if correlation is not None and correlation < 0.85 else "OK",
    }


def compare_canonical_files(
    base_path: Path, other_path: Path, *, base_label: str, other_label: str
) -> dict[str, Any]:
    return compare_price_series(
        load_canonical_csv(base_path), load_canonical_csv(other_path), base_label=base_label, other_label=other_label
    )
