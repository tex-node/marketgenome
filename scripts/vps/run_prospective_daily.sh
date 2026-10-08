#!/usr/bin/env bash
# Wrapper for the scheduled prospective daily run. Invoked by the
# market-genome-prospective.service systemd unit (see
# infrastructure/deployment/vps/systemd/). Kept as a script rather than a long
# inline ExecStart so the exact commands are version-controlled and testable by hand.
#
# Steps:
#   1. `prospective run-daily` -- acquisition -> derived-state rebuild (only if new
#      bars arrived) -> forecasts -> maturation -> evaluation snapshot. Real
#      (non-dry-run), idempotent, guarded by the application-level pg_try_advisory_lock
#      plus the RAM/swap/disk resource guard.
#   2. `generate_prospective_ledger.py` -- refresh forecast_ledger.csv and
#      run_history.csv from the database and the run's own audit artifacts, so the
#      scheduled cycle maintains its complete reporting artifact set with no manual step.
#   3. `generate_prospective_report.py` -- overwrite prospective_report.md with the
#      current evaluation state (headline + per-horizon metrics, trend, reading), so
#      the daily report is always current.
#
# `set -e` means each step runs only if the previous one succeeded: a resource-guard
# pause (exit 75) aborts the whole unit and is recorded as a failed run, exactly as
# before. A failure in any later step also fails the unit, so a broken artifact/refresh
# is surfaced rather than silent.
set -euo pipefail

ROOT="${MARKET_GENOME_ROOT:-/opt/market-genome}"
COMPOSE_FILE="$ROOT/app/infrastructure/deployment/vps/docker-compose.vps.yml"
ENV_FILE="${MARKET_GENOME_ENV_FILE:-$ROOT/config/market-genome.env}"
PROJECT_NAME="${MARKET_GENOME_COMPOSE_PROJECT:-market-genome}"
# Inside the worker container the report volume is always mounted at this path
# (see docker-compose.vps.yml), independent of the host-side report root.
CONTAINER_REPORT_DIR="/opt/market-genome/reports/prospective_context_validation"

cd "$ROOT/app/infrastructure/deployment/vps"
DC=(docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

"${DC[@]}" run --rm -T worker market-genome prospective run-daily

"${DC[@]}" run --rm -T worker python scripts/generate_prospective_ledger.py --output-dir "$CONTAINER_REPORT_DIR"

"${DC[@]}" run --rm -T worker python scripts/generate_prospective_report.py --output-dir "$CONTAINER_REPORT_DIR"
