"""Reproducible prospective forecast ledger + daily-run audit artifact generator.

Reads directly from ProspectiveForecast/ProspectiveForecastOutcome rows -- entirely
derived from the database, never a source of truth itself. Safe to re-run at any
time; always overwrites the ledger with the full current set of forecasts for the
given protocol.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from market_genome_domain.database import SessionLocal
from market_genome_domain.models import (
    ProspectiveForecast,
    ProspectiveForecastOutcome,
    ProspectiveProtocol,
)
from sqlalchemy import text

LEDGER_FIELDS = [
    "forecast_id", "instrument", "pattern_window_id", "window_length", "forecast_timestamp", "created_at",
    "context", "context_level", "horizon", "probability_positive", "expected_return", "sample_count",
    "confidence_lower", "confidence_upper", "status", "matured_at", "actual_return",
]


def write_ledger(session, protocol_id: str, output_path: Path) -> int:
    forecasts = (
        session.query(ProspectiveForecast)
        .filter(ProspectiveForecast.protocol_id == protocol_id)
        .order_by(ProspectiveForecast.forecast_timestamp, ProspectiveForecast.instrument_id, ProspectiveForecast.window_length, ProspectiveForecast.horizon_bars)
        .all()
    )
    symbols = {
        row["id"]: row["symbol"]
        for row in session.execute(text("select id::text as id, symbol from instruments")).mappings().all()
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS)
        writer.writeheader()
        for forecast in forecasts:
            outcome = (
                session.query(ProspectiveForecastOutcome)
                .filter(ProspectiveForecastOutcome.forecast_id == forecast.id)
                .one_or_none()
            )
            writer.writerow(
                {
                    "forecast_id": forecast.id,
                    "instrument": symbols.get(forecast.instrument_id, forecast.instrument_id),
                    "pattern_window_id": forecast.pattern_window_id,
                    "window_length": forecast.window_length,
                    "forecast_timestamp": forecast.forecast_timestamp.isoformat(),
                    "created_at": forecast.forecast_created_at.isoformat(),
                    "context": forecast.context_code,
                    "context_level": forecast.context_level_used,
                    "horizon": forecast.horizon_bars,
                    "probability_positive": float(forecast.probability_positive),
                    "expected_return": float(forecast.expected_return) if forecast.expected_return is not None else None,
                    "sample_count": forecast.sample_count,
                    "confidence_lower": float(forecast.confidence_lower),
                    "confidence_upper": float(forecast.confidence_upper),
                    "status": forecast.status,
                    "matured_at": outcome.matured_at.isoformat() if outcome is not None else None,
                    "actual_return": float(outcome.actual_return) if outcome is not None else None,
                }
            )
    return len(forecasts)


def write_run_history(output_dir: Path, history_path: Path) -> int:
    """Operational provenance, not a performance dashboard: one row per daily-run
    audit artifact already written by `market-genome prospective run-daily` (see
    prospective_daily_run_<timestamp>.json), answering "which days did Market Genome
    run, which instruments updated, how many forecasts were created, did any provider
    errors or data revisions occur" -- purely by reading those existing artifacts, so
    it can never disagree with them."""
    rows = []
    for path in sorted(output_dir.glob("prospective_daily_run_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "run_timestamp": payload.get("run_timestamp"),
                "artifact": path.name,
                "provider_code": payload.get("provider_code"),
                "instruments_with_new_bars": ",".join(
                    sorted(symbol for symbol, count in (payload.get("new_bars_by_instrument") or {}).items() if count)
                ),
                "new_forecast_count": payload.get("new_forecast_count"),
                "matured_count_this_run": payload.get("matured_count_this_run"),
                "warnings": json.dumps(payload.get("warnings") or {}),
                "run_hash": payload.get("run_hash"),
            }
        )
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["run_timestamp", "artifact", "provider_code", "instruments_with_new_bars", "new_forecast_count", "matured_count_this_run", "warnings", "run_hash"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default="market_context_forecast_v1")
    parser.add_argument("--output-dir", default="research/reports/prospective_context_validation")
    args = parser.parse_args()

    with SessionLocal() as session:
        protocol = (
            session.query(ProspectiveProtocol)
            .filter(ProspectiveProtocol.protocol_code == args.protocol, ProspectiveProtocol.status == "FROZEN")
            .order_by(ProspectiveProtocol.created_at.desc())
            .first()
        )
        if protocol is None:
            raise SystemExit(f"NO_FROZEN_PROTOCOL:{args.protocol}")

        output_dir = Path(args.output_dir)
        ledger_path = output_dir / "forecast_ledger.csv"
        count = write_ledger(session, protocol.id, ledger_path)

        history_path = output_dir / "run_history.csv"
        history_rows = write_run_history(output_dir, history_path)

        print(
            json.dumps(
                {"ledger_path": str(ledger_path), "ledger_rows": count, "run_history_path": str(history_path), "run_history_rows": history_rows},
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
