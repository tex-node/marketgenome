from __future__ import annotations

from market_genome_prospective.timing_analysis import (
    MINIMUM_WEEKDAY_OBSERVATIONS,
    analyze_timing_observations,
    is_weekend,
    result_to_dict,
)

# Real calendar week: Mon 2026-08-17 .. Sun 2026-08-23.
DATE_BY_DAY = {
    "Monday": "2026-08-17", "Tuesday": "2026-08-18", "Wednesday": "2026-08-19",
    "Thursday": "2026-08-20", "Friday": "2026-08-21", "Saturday": "2026-08-22", "Sunday": "2026-08-23",
}


def test_is_weekend_classifies_saturday_and_sunday() -> None:
    assert is_weekend("Saturday") is True
    assert is_weekend("Sunday") is True
    assert is_weekend("Monday") is False
    assert is_weekend("Friday") is False


def _row(
    instrument: str, day: str, time: str, provider_latest_date: str = "2026-08-15", reachable: bool = True, new_bar: bool = True
) -> dict:
    return {
        "observation_timestamp_utc": f"{DATE_BY_DAY[day]}T{time}+00:00",
        "instrument": instrument,
        "day_of_week": day,
        "provider_latest_date": provider_latest_date,
        "new_completed_bar_available": new_bar,
        "provider_reachable": reachable,
    }


def test_insufficient_weekday_observations_yields_not_yet_validated() -> None:
    rows = [_row("EURUSD_AV", "Monday", "04:00:00")]

    result = analyze_timing_observations(rows)

    assert result.weekday_observation_count == 1
    assert result.validation_status == "SCHEDULER_TIMING_NOT_YET_VALIDATED"
    assert result.candidate_safe_time_utc is None
    assert any("weekday" in limitation for limitation in result.limitations)


def test_weekend_observations_do_not_count_toward_weekday_minimum() -> None:
    rows = [_row("BTCUSD_AV", "Saturday", "04:00:00"), _row("BTCUSD_AV", "Sunday", "04:00:00")]

    result = analyze_timing_observations(rows)

    assert result.weekday_observation_count == 0
    assert result.weekend_observation_count == 2
    assert result.validation_status == "SCHEDULER_TIMING_NOT_YET_VALIDATED"


def test_multiple_instruments_checked_once_on_the_same_day_count_as_one_observation() -> None:
    """Regression guard for a real bug caught live on 2026-08-24: checking all 6
    instruments once on a single Monday must NOT satisfy the 3-weekday minimum. The
    minimum exists to require evidence spread across multiple different real days,
    not multiple instruments checked once on the same day."""
    rows = [_row(symbol, "Monday", "05:00:00") for symbol in ["EURUSD_AV", "GBPUSD_AV", "USDJPY_AV", "AUDUSD_AV", "BTCUSD_AV", "ETHUSD_AV"]]

    result = analyze_timing_observations(rows)

    assert result.observation_count == 6
    assert result.weekday_observation_count == 1  # one distinct calendar date, not six rows
    assert result.validation_status == "SCHEDULER_TIMING_NOT_YET_VALIDATED"


def test_sufficient_weekday_observations_across_distinct_days_yields_validated() -> None:
    rows = [
        _row("EURUSD_AV", "Monday", "06:15:00"),
        _row("EURUSD_AV", "Tuesday", "06:05:00"),
        _row("EURUSD_AV", "Wednesday", "06:20:00"),
        _row("BTCUSD_AV", "Monday", "04:10:00"),
        _row("BTCUSD_AV", "Tuesday", "04:05:00"),
        _row("BTCUSD_AV", "Wednesday", "04:00:00"),
    ]

    result = analyze_timing_observations(rows)

    assert result.weekday_observation_count == MINIMUM_WEEKDAY_OBSERVATIONS  # 3 distinct days, not 6 rows
    assert result.validation_status == "SCHEDULER_TIMING_VALIDATED"
    # The slowest instrument (EURUSD_AV, earliest observed at 06:05) governs the
    # candidate time, plus the fixed safety margin -- not the fastest instrument.
    assert result.candidate_safe_time_utc == "08:05"


def test_stale_carryover_check_never_anchors_earliest_observed_time() -> None:
    """Regression guard for a real bug caught live on 2026-08-27: an early-morning
    weekend check that just re-confirms an already-known date (new_completed_bar_available
    = False -- e.g. FX still showing Friday's close) is not a publication-timing event
    at all and must never set an instrument's "earliest observed availability". Only
    rows where a bar genuinely newer than what was already known became available may
    anchor that calculation, or a scheduler time derived from it could run before the
    instrument's data has ever actually been observed to be ready."""
    rows = [
        _row("EURUSD_AV", "Sunday", "04:36:00", new_bar=False),  # stale carry-over, must be ignored
        _row("EURUSD_AV", "Monday", "05:23:00", new_bar=False),  # still stale
        _row("EURUSD_AV", "Wednesday", "09:16:00", new_bar=True),  # first genuine new-bar event
        _row("EURUSD_AV", "Thursday", "21:01:00", new_bar=True),
        _row("BTCUSD_AV", "Sunday", "04:38:00", new_bar=False),
        _row("BTCUSD_AV", "Monday", "05:23:00", new_bar=True),
        _row("BTCUSD_AV", "Wednesday", "09:16:00", new_bar=True),
        _row("BTCUSD_AV", "Thursday", "21:01:00", new_bar=True),
    ]

    result = analyze_timing_observations(rows)

    eurusd = next(s for s in result.instrument_summaries if s.instrument == "EURUSD_AV")
    assert eurusd.earliest_observed_availability_utc == "09:16:00"  # not the 04:36 stale check
    assert result.validation_status == "SCHEDULER_TIMING_VALIDATED"  # 3 distinct weekdays: Mon, Wed, Thu
    # EURUSD_AV's genuine-earliest (09:16) is later than BTCUSD_AV's (05:23), so it
    # governs the conservative candidate time, not the faster instrument.
    assert result.candidate_safe_time_utc == "11:16"


def test_instrument_with_only_stale_observations_blocks_validation() -> None:
    """If an instrument has been checked but never once shown a genuine new bar, its
    publication timing is completely unknown -- validating anyway would silently
    ignore that instrument's true (possibly much later) publication time."""
    rows = [
        _row("EURUSD_AV", "Monday", "06:00:00", new_bar=False),
        _row("EURUSD_AV", "Tuesday", "06:00:00", new_bar=False),
        _row("EURUSD_AV", "Wednesday", "06:00:00", new_bar=False),
        _row("BTCUSD_AV", "Monday", "04:00:00", new_bar=True),
        _row("BTCUSD_AV", "Tuesday", "04:00:00", new_bar=True),
        _row("BTCUSD_AV", "Wednesday", "04:00:00", new_bar=True),
    ]

    result = analyze_timing_observations(rows)

    assert result.weekday_observation_count == 3
    assert result.validation_status == "SCHEDULER_TIMING_NOT_YET_VALIDATED"
    assert any("no genuine new-bar observation" in limitation and "EURUSD_AV" in limitation for limitation in result.limitations)


def test_unreachable_observations_are_excluded_from_counts() -> None:
    rows = [_row("EURUSD_AV", "Monday", "06:00:00", reachable=False)]

    result = analyze_timing_observations(rows)

    assert result.observation_count == 0
    assert result.weekday_observation_count == 0
    assert any("no reachable observations" in limitation for limitation in result.limitations)


def test_result_to_dict_round_trips_all_fields() -> None:
    rows = [_row("EURUSD_AV", "Monday", "06:00:00")]

    payload = result_to_dict(analyze_timing_observations(rows))

    assert payload["observation_count"] == 1
    assert payload["instrument_summaries"][0]["instrument"] == "EURUSD_AV"
    assert "validation_status" in payload
    assert "limitations" in payload
