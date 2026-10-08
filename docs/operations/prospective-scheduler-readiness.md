# Prospective Scheduler Readiness

Step 10B-C.2 hardened the daily prospective workflow and evaluated it against the scheduler-readiness checklist below. The scheduler was subsequently **activated on 2026-09-12** (with explicit authorization) as a systemd timer on the VPS host -- see [Activated scheduler](#activated-scheduler-2026-09-12).

## Readiness checklist

| Gate | Result | Evidence |
|---|---|---|
| A. Provider key delivered securely | PASS | `ALPHA_VANTAGE_API_KEY` persisted in `market-genome.env`, passed through the worker's `environment:` block, verified reachable via `data provider-smoke`; confirmed absent everywhere else on the VPS filesystem via full recursive grep. |
| B. Provider failure safe | PASS | Per-instrument `try/except` around the fetch call; a failure sets `acquisition_error` on that instrument's entry only and the loop continues for the rest. Verified by source inspection and by construction (unaffected in both live runs). |
| C. Rate limit safe | PASS | `classify_provider_error` recognizes `RATE_LIMITED`/`Note`/`Information` provider responses and returns `PROVIDER_RATE_LIMITED` without retrying indefinitely; `_download_with_retries` treats `AlphaVantageProviderError` as non-retryable (raises immediately) precisely to avoid burning quota on a rate-limit response. Covered by existing unit tests. |
| D. No-new-bar day safe | PASS (live) | Second live run (`new_bars_imported: 0` for all 6 instruments) completed cleanly with no errors and no forecast/window/context duplication. |
| E. Mixed FX/crypto calendar safe | PASS (live) | Single real run processed 4 stale-but-no-new-data FX instruments and 2 genuinely-advanced crypto instruments in the same invocation without any special-casing or failure. |
| F. Duplicate provider response safe | PASS | `persist_csv_import` checks for an existing `PriceBar` by (instrument, timeframe, source, timestamp) before inserting; a duplicate row is tagged and skipped, never re-inserted. Verified live (0 new price_bars on the repeat run). |
| G. Daily run idempotent | PASS (live) | Repeat live run: every protected table (`price_bars`, `pattern_windows`, `normalized_patterns`, `market_dna`, `market_contexts`, `outcome_observations`, `prospective_forecasts`, `prospective_forecast_outcomes`) identical before/after; only `prospective_evaluation_snapshots` grew by 1 (an evaluation snapshot is intentionally refreshed every real run, even with zero new forecasts). |
| H. Incremental processing only | PASS | Derived-state rebuild (`WindowBuildService`/.../`OutcomeBuildService`) only runs per instrument when `bars_after > bars_before`; live runs created only 6-18 new derived rows per table against a base of 500K+, never a full rebuild. |
| I. Concurrent-run lock present | PASS (live) | `pg_try_advisory_lock`/`pg_advisory_unlock` around real (non-dry-run) executions. Verified live: a genuinely held lock caused a second invocation to report `PROSPECTIVE_RUN_ALREADY_ACTIVE` and exit; the lock released the instant the holding session ended. |
| J. Crash recovery safe | PASS (live) | Simulated a crashed worker by forcibly terminating (`pg_terminate_backend`) a session holding the lock -- the advisory lock released immediately (Postgres releases session-level advisory locks on connection termination, by design). Data-layer crash safety relies on each acquisition/build step's own established commit-per-unit-of-work and idempotent incremental-mode behavior from earlier phases. |
| K. Forecast guard safe | PASS | Retroactive-creation guard (`RETROACTIVE_PROSPECTIVE_FORECAST_REJECTED`) and identity (`protocol_id`+`pattern_window_id`+`horizon_bars`+`provenance_class`) unchanged this phase; both live runs' 72 new forecasts passed 0-violation integrity checks. |
| L. Maturation safe | PASS | Maturation keyed by `pattern_window_id`+`horizon_bars`, never timestamp equality; re-running `mature` produces 0 duplicate outcomes when nothing is newly eligible (verified in earlier phase and unchanged here). |
| M. Evaluation provenance safe | PASS | `create_evaluation_snapshot` filters `provenance_class == TRUE_PROSPECTIVE` (verified prior phase); status correctly stayed `PROSPECTIVE_EVIDENCE_ACCUMULATING` throughout. |
| N. Artifact generation safe | PASS | `run-daily` now writes its own `prospective_daily_run_<timestamp>.json` directly (precise before/after forecast-ID set diff, not a fuzzy time window); ledger and run-history generators verified to reference no secret env vars (regression test). |
| O. Resource guard safe | PASS | RAM/swap guard unchanged; disk-free guard added this phase (`--min-free-disk-mb`, default 15GB) via an opt-in extension to `evaluate_resource_guard` that leaves the other existing caller (`studies prepare-data`) untouched. |
| P. Secrets absent from logs/artifacts | PASS | Full recursive filesystem grep for the raw key found zero matches outside the env file; defensive `_redact_secrets()` added at the two CLI error-surfacing call sites that echo raw exception text, verified urllib/AlphaVantageProviderError never embed the key in any exception message. |

**SCHEDULER_READY = YES** on engineering/mechanism grounds. Activation was separately authorized on 2026-09-12 (see below).

## Scheduler timing

**SCHEDULER_TIMING_VALIDATED** (validated 2026-08-31). Candidate safe time **`11:16 UTC`**, stable across 9 weekday and 2 weekend provider-availability observations. The calculation only anchors on observations where a genuinely new completed bar was observed, requires every observed instrument to have at least one such genuine observation before validating, and counts distinct calendar dates rather than raw observation rows (all three were earlier bugs, fixed and regression-tested). See `SESSION.md` for the observation history.

The single 2026-08-23 observation previously recorded here as `NOT_YET_VALIDATED` is superseded.

## Activated scheduler (2026-09-12)

Activated with explicit authorization as a **systemd timer + oneshot service on the VPS host** (not a long-running sleep loop).

- Version-controlled files:
  - `infrastructure/deployment/vps/systemd/market-genome-prospective.service`
  - `infrastructure/deployment/vps/systemd/market-genome-prospective.timer`
  - `scripts/vps/run_prospective_daily.sh` (wrapper: runs `docker compose ... run --rm -T worker market-genome prospective run-daily`, then regenerates `forecast_ledger.csv`/`run_history.csv` via `generate_prospective_ledger.py`, then overwrites `prospective_report.md` via `generate_prospective_report.py`)
- Installed at `/etc/systemd/system/`; the copies under `/opt/market-genome/app/...` are the source of truth to re-copy from.
- Schedule: `OnCalendar=*-*-* 11:16:00 UTC`, `Persistent=true` (a missed day runs once on next boot), `AccuracySec=1min`.
- Behavior: `Type=oneshot`, `TimeoutStartSec=2400`, `Restart=no` -- no in-day auto-retry, so an automatic restart can never race the database advisory lock; the next timer fire is the natural retry. Success exits 0; a resource-guard failure exits non-zero (code 75) and is recorded as a failed unit run.
- Safety layers unchanged from the gates above: the database's `pg_try_advisory_lock` remains authoritative against overlap; the RAM/swap/disk guard remains a precondition; acquisition is provider-failure-safe and rate-limit-safe; derived state is rebuilt only when new bars actually arrived.
- Logs: `journalctl -u market-genome-prospective.service`. The authoritative operational record remains the run's own JSON report plus `prospective_daily_run_*.json`, `forecast_ledger.csv`, and `run_history.csv`; the wrapper regenerates the ledger/run-history and overwrites the human-readable `prospective_report.md` after each successful run, so the scheduled cycle keeps the full artifact set current without a manual step.

### Installation / update

From the app root on the VPS (`/opt/market-genome/app`):

```bash
cp infrastructure/deployment/vps/systemd/market-genome-prospective.* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now market-genome-prospective.timer
systemctl list-timers market-genome-prospective.timer
```

Note: the `worker` image bakes source in at build time, so after any code change run `docker compose build worker` before the next scheduled fire, or the timer will keep running the previous image.
