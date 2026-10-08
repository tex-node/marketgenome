from __future__ import annotations

import pandas as pd
from hypothesis import given
from hypothesis import strategies as st
from market_genome_data_ingestion.providers.yahoo_finance import (
    canonical_csv_hash,
    canonicalize_yahoo_frame,
)
from market_genome_shared.hashing import sha256_canonical


def _frame(order: list[int]) -> pd.DataFrame:
    dates = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    base = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, 102.5],
            "Volume": [1000, 1100, 1200],
        },
        index=dates,
    )
    base.index.name = "Date"
    return base.iloc[order]


@given(st.permutations([0, 1, 2]))
def test_row_ordering_does_not_change_canonical_hash(order: list[int]) -> None:
    assert canonical_csv_hash(canonicalize_yahoo_frame(_frame(list(order)))) == canonical_csv_hash(canonicalize_yahoo_frame(_frame([0, 1, 2])))


def test_changing_acquired_value_changes_hash() -> None:
    original = canonicalize_yahoo_frame(_frame([0, 1, 2]))
    changed = original.copy()
    changed.loc[1, "close"] += 1.0

    assert canonical_csv_hash(original) != canonical_csv_hash(changed)


def test_manifest_hash_determinism_for_equivalent_key_order() -> None:
    left = {"provider": {"code": "yahoo_finance_v1"}, "manifest": {"code": "x"}}
    right = {"manifest": {"code": "x"}, "provider": {"code": "yahoo_finance_v1"}}

    assert sha256_canonical(left) == sha256_canonical(right)
