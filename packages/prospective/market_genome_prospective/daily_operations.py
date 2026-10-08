"""Pure, testable helpers for the daily prospective operations workflow.

Kept separate from market_genome_cli.main so the staleness/regression/plan-shape
logic that both --dry-run and a real run depend on can be unit tested without a
database, a provider, or a running container.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RUN_LOCK_NAME = "market_genome_prospective_run_daily"


def is_stale(latest_bar_date: str | None, today: str) -> bool:
    """A latest persisted bar date is stale once it is strictly before today -- the
    daily runner should attempt to acquire newer data for that instrument."""
    return latest_bar_date is None or latest_bar_date < today


def detect_provider_date_regression(persisted_latest_date: str | None, provider_latest_date: str | None) -> bool:
    """True when the provider's latest available date is older than what is already
    persisted -- this must never happen for an append-only historical feed, and must
    never be used to silently overwrite or delete the newer local data."""
    if persisted_latest_date is None or provider_latest_date is None:
        return False
    return provider_latest_date < persisted_latest_date


@dataclass
class InstrumentDailyPlan:
    """The single per-instrument plan shape shared by --dry-run preview and the real
    run's execution decision, so the two can never diverge on what "stale" or
    "eligible to mature" means."""

    symbol: str
    provider_latest_date: str | None = None
    database_latest_date: str | None = None
    new_bar_count: int | str | None = None
    would_import: bool = False
    would_build_windows: bool = False
    would_build_context: bool = False
    would_create_forecasts: list[dict[str, Any]] = field(default_factory=list)
    pending_forecasts_eligible_to_mature: int = 0
    warnings: list[str] = field(default_factory=list)
    status: str = "PENDING"

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "provider_latest_date": self.provider_latest_date,
            "database_latest_date": self.database_latest_date,
            "new_bar_count": self.new_bar_count,
            "would_import": self.would_import,
            "would_build_windows": self.would_build_windows,
            "would_build_context": self.would_build_context,
            "would_create_forecasts": self.would_create_forecasts,
            "pending_forecasts_eligible_to_mature": self.pending_forecasts_eligible_to_mature,
            "warnings": self.warnings,
            "status": self.status,
        }


__all__ = ["RUN_LOCK_NAME", "InstrumentDailyPlan", "detect_provider_date_regression", "is_stale"]
