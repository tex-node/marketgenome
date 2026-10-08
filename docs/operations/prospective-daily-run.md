# Prospective Daily Run

`market-genome prospective run-daily` is the single deterministic entry point for advancing the prospective forecasting protocol one iteration: acquire the latest completed D1 bar (if a manifest is supplied and data is stale), rebuild derived state only when new bars actually arrived, create `TRUE_PROSPECTIVE` forecasts from the latest available window/context per instrument, mature eligible pending forecasts, and refresh the evaluation snapshot.

It is scheduled on the VPS via a systemd timer (`market-genome-prospective.timer`, daily at 11:16 UTC) whose wrapper script also refreshes the ledger artifacts; see [prospective-scheduler-readiness.md](prospective-scheduler-readiness.md). It can still be triggered manually at any time.

## Commands

```bash
market-genome prospective protocols
market-genome prospective create-protocol --protocol market_context_forecast_v1
market-genome prospective run-daily --dry-run
market-genome prospective run-daily
market-genome prospective forecast-only --dry-run
market-genome prospective forecast-only
market-genome prospective mature
market-genome prospective evaluate
market-genome prospective status
```

`run-daily` always defaults to a resource guard (minimum available RAM/swap/disk, the last added in Step 10B-C.2, default 15GB via `--min-free-disk-mb`) before doing anything; pass `--no-resource-guard` only for local testing.

A real (non-dry-run) invocation holds a Postgres session-level advisory lock for its duration, so two real runs against the same database can never overlap -- a second invocation sees `{"status": "PROSPECTIVE_RUN_ALREADY_ACTIVE"}` and exits immediately. The lock releases automatically if the process crashes (Postgres releases session-level advisory locks when the holding connection terminates, verified live via `pg_terminate_backend`), so no manual cleanup is ever needed after an abnormal exit. Dry runs are never locked -- concurrent previews are harmless.

Each instrument is processed independently: a provider failure, a rate-limited response, or a stale-but-unchanged instrument (weekend FX, for example) never blocks the other instruments in the same run. If the provider's latest available date for an instrument is ever older than what's already persisted (`PROVIDER_DATE_REGRESSION`), that instrument's fetch is skipped for this run -- existing data is never deleted or overwritten with older history.

Every real invocation writes its own `research/reports/prospective_context_validation/prospective_daily_run_<UTC timestamp>.json` audit artifact, with a precise (before/after set-diff, not time-window-based) list of forecast IDs created that run. `scripts/generate_prospective_ledger.py --output-dir <dir>` regenerates the full forecast ledger (`forecast_ledger.csv`, always derivable from the database) and a compact `run_history.csv` summarizing every daily-run artifact found in that directory -- operational provenance, not a performance dashboard. `scripts/generate_prospective_report.py --output-dir <dir>` overwrites a human-readable `prospective_report.md` (status, headline + per-horizon metrics, trend, reading) from the latest snapshot and run artifact. On the VPS the scheduler wrapper (`scripts/vps/run_prospective_daily.sh`) runs the ledger and report regeneration automatically right after a successful `run-daily`, so the scheduled cycle is self-contained (and a failure in either regeneration step fails the unit rather than passing silently).

## forecast-only

`forecast-only` creates forecasts from whichever windows/contexts already exist -- it never touches acquisition, never fetches from a provider, and never rebuilds windows/normalization/DNA/context/outcomes. Use it when acquisition has already run separately (or isn't needed) and only the forecast step should advance. It accepts `--provenance-class` (default `TRUE_PROSPECTIVE`); pass `BACKFILL_SIMULATION` or `HISTORICAL_VALIDATION` for smoke tests so they can never be counted as genuine prospective evidence.

## Provider credential

`ALPHA_VANTAGE_API_KEY` is persisted in the VPS's `market-genome.env` and passed through to the `worker` service's container environment (the `api` service never needs or receives it -- acquisition only happens via the CLI/worker). Without it, `run-daily` degrades gracefully (forecasts from the latest already-imported bar) rather than crashing.

See [prospective-scheduler-readiness.md](prospective-scheduler-readiness.md) for the full scheduler-readiness checklist and the activated scheduling design.

## Incident history

A `run-daily` bug once requested only the protocol's own (narrower) horizon subset for the outcome rebuild step, instead of the full research horizon set (`RESEARCH_OUTCOME_HORIZONS = [1, 3, 5, 10, 20, 40, 60]`). Because `OutcomeBuildService`'s configuration hash includes the exact requested-horizons list, this created 267,246 duplicate `outcome_observations` rows before being caught, authorized for deletion, and fixed. `run-daily` now always requests the full research horizon set and only rebuilds derived state when new bars were genuinely imported (`if bars_after > bars_before:`). See `tests/unit/test_prospective_cli_safety.py` for the regression guards.
