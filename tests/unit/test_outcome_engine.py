from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest
from market_genome_domain.models import PatternWindow, PriceBar
from market_genome_outcomes.service import compute_outcome, future_bar_hash


def _bar(index: int, close: float, high: float | None = None, low: float | None = None) -> PriceBar:
    return PriceBar(
        instrument_id="instrument",
        timeframe_id="H1",
        timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=index),
        open=close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
        volume=1000,
        source_id="source",
    )


def _window(end_index: int = 3) -> PatternWindow:
    return PatternWindow(
        id="window",
        instrument_id="instrument",
        timeframe_id="H1",
        start_timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        end_timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=end_index),
        start_bar_id="start",
        end_bar_id="end",
        window_length=4,
        stride=1,
        bar_count=4,
        source_data_hash="source-hash",
        build_configuration_hash="build-hash",
        quality_flags=[],
    )


def test_compute_outcome_uses_strictly_future_bars_and_anchor_close() -> None:
    window = _window()
    anchor = _bar(3, 100.0)
    future = [_bar(4, 105.0, high=106.0, low=99.0), _bar(5, 102.0, high=107.0, low=101.0)]

    outcome = compute_outcome(window, anchor, future, 2, source_return=0.03)

    assert outcome.diagnostics["anchor_excluded_from_future"] is True
    assert outcome.scalar_values["future_simple_return"] == pytest.approx(0.02)
    assert outcome.scalar_values["future_log_return"] == pytest.approx(math.log(1.02))
    assert outcome.scalar_values["maximum_favourable_excursion"] == pytest.approx(0.07)
    assert outcome.scalar_values["maximum_adverse_excursion"] == pytest.approx(-0.01)
    assert outcome.scalar_values["time_to_mfe_bars"] == 2
    assert outcome.scalar_values["time_to_mae_bars"] == 1
    assert outcome.forward_path["values"][0] == 0.0
    assert outcome.forward_path["values"][-1] == pytest.approx(outcome.scalar_values["future_log_return"])
    assert outcome.scalar_values["continuation_reversal_class"] == "CONTINUATION"


def test_outcome_rejects_anchor_or_past_bars_as_future() -> None:
    window = _window()
    anchor = _bar(3, 100.0)

    with pytest.raises(ValueError, match="OUTCOME_ANCHOR_BAR_MISMATCH"):
        compute_outcome(window, anchor, [_bar(3, 101.0)], 1)


def test_barriers_same_bar_and_volatility_horizon_one() -> None:
    window = _window()
    anchor = _bar(3, 100.0)
    future = [_bar(4, 100.5, high=102.0, low=98.0)]

    outcome = compute_outcome(window, anchor, future, 1, source_return=-0.02)

    assert outcome.scalar_values["future_realized_volatility"] is None
    assert outcome.scalar_values["first_barrier_hit"] == "SAME_BAR_BOTH"
    assert outcome.scalar_values["gain_before_drawdown"] == "SAME_BAR_BOTH"
    assert outcome.scalar_values["drawdown_before_gain"] == "SAME_BAR_BOTH"
    assert outcome.scalar_values["future_path_efficiency"] == pytest.approx(1.0)


def test_partial_outcome_is_flagged_and_hash_changes_with_future_data() -> None:
    window = _window()
    anchor = _bar(3, 100.0)
    partial = [_bar(4, 101.0)]
    complete = [_bar(4, 101.0), _bar(5, 103.0), _bar(6, 102.0)]

    partial_outcome = compute_outcome(window, anchor, partial, 3)
    complete_outcome = compute_outcome(window, anchor, complete, 3)

    assert partial_outcome.diagnostics["is_complete"] is False
    assert "PARTIAL_HORIZON" in partial_outcome.quality_flags
    assert complete_outcome.diagnostics["is_complete"] is True
    assert partial_outcome.future_bar_hash != complete_outcome.future_bar_hash
    assert future_bar_hash(partial) != future_bar_hash(complete)


def test_return_values_are_price_scale_invariant() -> None:
    window = _window()
    original = compute_outcome(_window(), _bar(3, 100), [_bar(4, 101), _bar(5, 103)], 2)
    scaled = compute_outcome(window, _bar(3, 1000), [_bar(4, 1010), _bar(5, 1030)], 2)

    keys = [
        "future_simple_return",
        "future_log_return",
        "maximum_favourable_excursion",
        "maximum_adverse_excursion",
        "future_path_efficiency",
    ]
    for key in keys:
        assert scaled.scalar_values[key] == pytest.approx(original.scalar_values[key])
