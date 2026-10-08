from __future__ import annotations

from market_genome_prospective.daily_operations import (
    InstrumentDailyPlan,
    detect_provider_date_regression,
    is_stale,
)


def test_is_stale_true_when_no_bar_persisted_yet() -> None:
    assert is_stale(None, "2026-08-23") is True


def test_is_stale_true_when_latest_bar_before_today() -> None:
    assert is_stale("2026-08-22", "2026-08-23") is True


def test_is_stale_false_when_latest_bar_is_today() -> None:
    assert is_stale("2026-08-23", "2026-08-23") is False


def test_detect_provider_date_regression_false_when_dates_unknown() -> None:
    assert detect_provider_date_regression(None, "2026-08-23") is False
    assert detect_provider_date_regression("2026-08-23", None) is False


def test_detect_provider_date_regression_false_when_provider_matches_or_advances() -> None:
    assert detect_provider_date_regression("2026-08-22", "2026-08-22") is False
    assert detect_provider_date_regression("2026-08-22", "2026-08-23") is False


def test_detect_provider_date_regression_true_when_provider_is_older() -> None:
    """The provider must never appear to have gone backwards relative to what is
    already persisted -- this signals a provider-side anomaly, not fresher data."""
    assert detect_provider_date_regression("2026-08-22", "2026-08-20") is True


def test_instrument_daily_plan_as_dict_round_trips_all_fields() -> None:
    plan = InstrumentDailyPlan(
        symbol="EURUSD_AV",
        provider_latest_date="2026-08-22",
        database_latest_date="2026-08-20",
        new_bar_count="UNKNOWN_UNTIL_ACQUISITION_RUNS",
        would_import=True,
        would_build_windows=True,
        would_build_context=True,
        would_create_forecasts=[{"window_length": 16, "horizon": 5, "would_create": True}],
        pending_forecasts_eligible_to_mature=0,
        warnings=[],
        status="STALE",
    )

    payload = plan.as_dict()

    assert payload["symbol"] == "EURUSD_AV"
    assert payload["would_import"] is True
    assert payload["would_create_forecasts"] == [{"window_length": 16, "horizon": 5, "would_create": True}]
    assert payload["status"] == "STALE"


def test_instrument_daily_plan_defaults_are_safe_and_empty() -> None:
    plan = InstrumentDailyPlan(symbol="GBPUSD_AV")

    assert plan.would_import is False
    assert plan.would_create_forecasts == []
    assert plan.warnings == []
    assert plan.pending_forecasts_eligible_to_mature == 0
