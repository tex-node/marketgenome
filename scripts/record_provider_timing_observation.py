"""Bounded, append-only provider D1-publication-timing observation.

Records one row per instrument per invocation to a durable CSV so scheduler timing
can eventually be validated from real, repeated observations -- never fabricated,
never backfilled. Does not persist market data to the database; the underlying
provider.fetch() call writes only a throwaway temp-directory CSV used to read the
publication date, which is discarded when the process exits.
"""
from __future__ import annotations

import argparse
import csv
import json
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from market_genome_data_ingestion.acquisition import classify_provider_error
from market_genome_data_ingestion.providers.base import HistoricalDataRequest, get_provider
from market_genome_prospective.timing_analysis import analyze_timing_observations, result_to_dict

# Alpha Vantage's free tier enforces ~5 requests/minute; the production acquisition
# manifest (research/data/manifests/independent_replication_v1.yaml) already spaces
# requests 15s apart for exactly this reason. Observing all 6 instruments back-to-back
# with no delay self-inflicts PROVIDER_RATE_LIMITED on the later ones (seen live on
# 2026-08-23: USDJPY_AV and BTCUSD_AV both rate-limited when this constant was 0).
INTER_INSTRUMENT_DELAY_SECONDS = 15

FIELDS = [
    "observation_timestamp_utc", "provider_code", "instrument", "asset_class", "day_of_week",
    "provider_latest_date", "database_latest_date", "new_completed_bar_available",
    "provider_reachable", "provider_status", "warnings",
]

# canonical symbol -> (provider symbol, asset class), matching the frozen protocol's
# instrument_universe (packages/prospective/market_genome_prospective/definitions.py)
DEFAULT_INSTRUMENTS = {
    "EURUSD_AV": ("EUR/USD", "forex"),
    "GBPUSD_AV": ("GBP/USD", "forex"),
    "USDJPY_AV": ("USD/JPY", "forex"),
    "AUDUSD_AV": ("AUD/USD", "forex"),
    "BTCUSD_AV": ("BTC/USD", "crypto"),
    "ETHUSD_AV": ("ETH/USD", "crypto"),
}


def _database_latest_date(session, symbol: str) -> str | None:
    from sqlalchemy import text

    row = session.execute(
        text(
            """
            select max(pb.timestamp) as latest from price_bars pb
            join instruments i on i.id = pb.instrument_id
            where i.symbol = :symbol
            """
        ),
        {"symbol": symbol},
    ).mappings().one()
    latest = row["latest"]
    return latest.strftime("%Y-%m-%d") if latest is not None else None


def observe(session, provider_code: str, instruments: dict[str, tuple[str, str]]) -> list[dict[str, object]]:
    provider = get_provider(provider_code)
    now = datetime.now(UTC)
    rows = []
    for index, (symbol, (provider_symbol, asset_class)) in enumerate(instruments.items()):
        if index:
            time.sleep(INTER_INSTRUMENT_DELAY_SECONDS)
        database_latest_date = _database_latest_date(session, symbol)
        with tempfile.TemporaryDirectory() as tmp_dir:
            request = HistoricalDataRequest(
                provider_symbol=provider_symbol, canonical_symbol=f"TIMING_{symbol}", instrument_name=symbol,
                asset_class=asset_class, exchange="TIMING", currency="USD", timezone="UTC", timeframe="D1",
                start="2024-01-01", end=now.strftime("%Y-%m-%d"), auto_adjust=False, include_actions=False,
                volume_type="unavailable" if asset_class == "forex" else "unknown",
                price_adjustment_basis="provider_unadjusted_raw", output_directory=Path(tmp_dir),
                delay_seconds=0, maximum_retries=0,
            )
            try:
                result = provider.fetch(request)
                provider_latest_date = result.received_end[:10] if result.received_end else None
                rows.append(
                    {
                        "observation_timestamp_utc": now.isoformat(),
                        "provider_code": provider_code,
                        "instrument": symbol,
                        "asset_class": asset_class,
                        "day_of_week": now.strftime("%A"),
                        "provider_latest_date": provider_latest_date,
                        "database_latest_date": database_latest_date,
                        "new_completed_bar_available": bool(
                            provider_latest_date and (database_latest_date is None or provider_latest_date > database_latest_date)
                        ),
                        "provider_reachable": True,
                        "provider_status": result.status,
                        "warnings": ";".join(result.warnings or []),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                rows.append(
                    {
                        "observation_timestamp_utc": now.isoformat(),
                        "provider_code": provider_code,
                        "instrument": symbol,
                        "asset_class": asset_class,
                        "day_of_week": now.strftime("%A"),
                        "provider_latest_date": None,
                        "database_latest_date": database_latest_date,
                        "new_completed_bar_available": False,
                        "provider_reachable": False,
                        "provider_status": classify_provider_error(exc),
                        "warnings": "",
                    }
                )
    return rows


def append_rows(output_path: Path, rows: list[dict[str, object]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not output_path.exists()
    with output_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def write_timing_analysis(observations_path: Path, analysis_path: Path) -> dict:
    """Always regenerated from the complete observation history in the CSV -- never
    from just this invocation's new rows -- so the analysis can only get more (never
    less) evidence-backed over time."""
    all_rows: list[dict] = []
    if observations_path.exists():
        with observations_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                row["provider_reachable"] = row["provider_reachable"] == "True"
                row["new_completed_bar_available"] = row["new_completed_bar_available"] == "True"
                all_rows.append(row)
    result = analyze_timing_observations(all_rows)
    payload = result_to_dict(result)
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    analysis_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="alpha_vantage_v1")
    parser.add_argument("--output", default="research/reports/prospective_context_validation/provider_timing_observations.csv")
    parser.add_argument("--analysis-output", default="research/reports/prospective_context_validation/scheduler_timing_analysis.json")
    parser.add_argument("--instrument", action="append", help="Limit to specific canonical symbols (repeatable); default is all 6.")
    args = parser.parse_args()

    from market_genome_domain.database import SessionLocal

    instruments = DEFAULT_INSTRUMENTS
    if args.instrument:
        instruments = {symbol: DEFAULT_INSTRUMENTS[symbol] for symbol in args.instrument}

    with SessionLocal() as session:
        rows = observe(session, args.provider, instruments)

    output_path = Path(args.output)
    append_rows(output_path, rows)
    print(f"Recorded {len(rows)} observation(s) to {output_path}")
    for row in rows:
        print(f"  {row['instrument']}: provider_latest_date={row['provider_latest_date']} new_bar={row['new_completed_bar_available']} status={row['provider_status']}")

    analysis = write_timing_analysis(output_path, Path(args.analysis_output))
    print(f"Timing analysis ({args.analysis_output}): {analysis['validation_status']}, "
          f"{analysis['weekday_observation_count']} weekday / {analysis['weekend_observation_count']} weekend observations")


if __name__ == "__main__":
    main()
