"""Pure, testable logic for scheduler-timing observation analysis.

Deliberately conservative: every "earliest observed availability" is a lower bound
(the earliest time we happened to check and already saw that date's bar), never a
claim about the actual publication instant, since that was never directly observed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

WEEKEND_DAYS = {"Saturday", "Sunday"}
MINIMUM_WEEKDAY_OBSERVATIONS = 3
PREFERRED_WEEKDAY_OBSERVATIONS = 5
SAFETY_MARGIN_HOURS = 2


def is_weekend(day_of_week: str) -> bool:
    return day_of_week in WEEKEND_DAYS


@dataclass
class InstrumentTimingSummary:
    instrument: str
    observation_count: int
    earliest_observed_availability_utc: str | None
    latest_observed_availability_utc: str | None


@dataclass
class TimingAnalysisResult:
    observation_count: int
    weekday_observation_count: int
    weekend_observation_count: int
    instrument_summaries: list[InstrumentTimingSummary] = field(default_factory=list)
    candidate_safe_time_utc: str | None = None
    validation_status: str = "SCHEDULER_TIMING_NOT_YET_VALIDATED"
    limitations: list[str] = field(default_factory=list)


def _time_of_day(observation_timestamp_utc: str) -> str:
    return observation_timestamp_utc.split("T", 1)[1][:8] if "T" in observation_timestamp_utc else observation_timestamp_utc


def _calendar_date(observation_timestamp_utc: str) -> str:
    return observation_timestamp_utc.split("T", 1)[0] if "T" in observation_timestamp_utc else observation_timestamp_utc


def analyze_timing_observations(rows: list[dict]) -> TimingAnalysisResult:
    """rows: [{"observation_timestamp_utc": iso8601, "instrument": str, "day_of_week": str,
    "provider_latest_date": str|None, "new_completed_bar_available": bool, "provider_reachable": bool}, ...]

    weekday/weekend counts are DISTINCT CALENDAR DATES, not row counts -- checking all
    6 instruments once on a single Monday must never count as "3 weekday observations".
    The whole point of the minimum is evidence spread across multiple different real
    days, not multiple instruments checked once on the same day."""
    reachable_rows = [r for r in rows if r.get("provider_reachable")]
    weekday_dates: set[str] = set()
    weekend_dates: set[str] = set()
    for r in reachable_rows:
        date = _calendar_date(r["observation_timestamp_utc"])
        (weekend_dates if is_weekend(r.get("day_of_week", "")) else weekday_dates).add(date)
    weekday_count = len(weekday_dates)
    weekend_count = len(weekend_dates)

    by_instrument: dict[str, list[dict]] = {}
    for row in reachable_rows:
        by_instrument.setdefault(row["instrument"], []).append(row)

    summaries = []
    per_instrument_earliest_times: list[str] = []
    instruments_with_no_genuine_new_bar_observation: list[str] = []
    for instrument, instrument_rows in sorted(by_instrument.items()):
        # Only rows where a bar genuinely newer than what was already known became
        # available are evidence of *publication timing* -- a row that just re-confirms
        # an already-known date (e.g. an FX check on a weekend, still showing Friday's
        # close) is not a timing observation at all and must never anchor the "earliest
        # observed availability" calculation, or a scheduler time derived from it could
        # run before that instrument's data has ever actually been seen to be ready.
        genuine_rows = [r for r in instrument_rows if r.get("new_completed_bar_available")]
        times = sorted(_time_of_day(r["observation_timestamp_utc"]) for r in genuine_rows)
        earliest = times[0] if times else None
        latest = times[-1] if times else None
        summaries.append(
            InstrumentTimingSummary(
                instrument=instrument, observation_count=len(instrument_rows),
                earliest_observed_availability_utc=earliest, latest_observed_availability_utc=latest,
            )
        )
        if earliest is not None:
            per_instrument_earliest_times.append(earliest)
        else:
            instruments_with_no_genuine_new_bar_observation.append(instrument)

    result = TimingAnalysisResult(
        observation_count=len(reachable_rows), weekday_observation_count=weekday_count,
        weekend_observation_count=weekend_count, instrument_summaries=summaries,
    )

    limitations = []
    if weekday_count < MINIMUM_WEEKDAY_OBSERVATIONS:
        limitations.append(f"only {weekday_count} weekday observation(s); minimum {MINIMUM_WEEKDAY_OBSERVATIONS} required")
    if weekday_count < PREFERRED_WEEKDAY_OBSERVATIONS:
        limitations.append(f"below the preferred {PREFERRED_WEEKDAY_OBSERVATIONS} weekday observations")
    instruments_observed = set(by_instrument.keys())
    if not instruments_observed:
        limitations.append("no reachable observations recorded yet")
    if instruments_with_no_genuine_new_bar_observation:
        limitations.append(
            "no genuine new-bar observation yet for: " + ", ".join(sorted(instruments_with_no_genuine_new_bar_observation))
        )
    result.limitations = limitations

    # Every observed instrument must have contributed at least one genuine new-bar
    # observation -- if even one instrument has none, the "slowest instrument governs"
    # logic below would silently ignore it, potentially understating how late that
    # instrument actually publishes.
    all_instruments_have_genuine_observation = not instruments_with_no_genuine_new_bar_observation and bool(by_instrument)
    if weekday_count >= MINIMUM_WEEKDAY_OBSERVATIONS and all_instruments_have_genuine_observation:
        # The conservative candidate time is the LATEST of the per-instrument earliest-
        # observed times (the slowest-to-publish instrument governs), plus a margin.
        slowest_time = max(per_instrument_earliest_times)
        hour, minute = int(slowest_time[:2]), int(slowest_time[3:5])
        candidate_hour = (hour + SAFETY_MARGIN_HOURS) % 24
        result.candidate_safe_time_utc = f"{candidate_hour:02d}:{minute:02d}"
        result.validation_status = "SCHEDULER_TIMING_VALIDATED"
    else:
        result.validation_status = "SCHEDULER_TIMING_NOT_YET_VALIDATED"

    return result


def _summary_to_dict(summary: InstrumentTimingSummary) -> dict:
    return {
        "instrument": summary.instrument,
        "observation_count": summary.observation_count,
        "earliest_observed_availability_utc": summary.earliest_observed_availability_utc,
        "latest_observed_availability_utc": summary.latest_observed_availability_utc,
    }


def result_to_dict(result: TimingAnalysisResult) -> dict:
    return {
        "observation_count": result.observation_count,
        "weekday_observation_count": result.weekday_observation_count,
        "weekend_observation_count": result.weekend_observation_count,
        "instrument_summaries": [_summary_to_dict(s) for s in result.instrument_summaries],
        "candidate_safe_time_utc": result.candidate_safe_time_utc,
        "validation_status": result.validation_status,
        "limitations": result.limitations,
    }


__all__ = [
    "MINIMUM_WEEKDAY_OBSERVATIONS",
    "PREFERRED_WEEKDAY_OBSERVATIONS",
    "InstrumentTimingSummary",
    "TimingAnalysisResult",
    "analyze_timing_observations",
    "is_weekend",
    "result_to_dict",
]
