# Prospective Context Forecasting

`ProspectiveContextForecastService` produces genuinely forward-looking probability estimates from the transparent Market Context engine alone. Market DNA is deliberately excluded from the primary forecast (Step 10A.4 found no incremental value once Market Context is already conditioned on). No trading logic, no learned models.

## Identity

A `ProspectiveForecast`'s unique identity is `(protocol_id, pattern_window_id, horizon_bars, provenance_class)`. `pattern_window_id` references one immutable `PatternWindow` row and already uniquely implies instrument, timeframe, window length, and query timestamp, so those fields are not repeated in the identity. `provenance_class` is included so the same pattern window and horizon can carry one `TRUE_PROSPECTIVE` forecast and, separately, one `BACKFILL_SIMULATION` or `HISTORICAL_VALIDATION` forecast without colliding.

## Timestamps

- `forecast_timestamp` -- the query window's `end_timestamp`; the point in time the forecast is *about*.
- `data_cutoff_timestamp` -- the latest data the estimate is permitted to use (historical-as-of boundary for the underlying `historical_probability` query).
- `forecast_created_at` -- when the forecast row was actually written; for `TRUE_PROSPECTIVE` this must be `>= data_cutoff_timestamp`.

## Estimation

`historical_probability` walks the protocol's frozen fallback hierarchy (most-specific context definition first) and returns the first level meeting `minimum_historical_sample`, falling back toward `unconditional` otherwise. The count itself is Beta-Binomial (Laplace, alpha=beta=1) smoothed; confidence bounds are a Wilson interval, not a naive normal approximation. All matching windows must satisfy `end_timestamp < as_of` -- no future data ever contributes to a probability estimate.

## Maturation

`mature_forecast` attaches the matching completed `OutcomeObservation` (by `pattern_window_id` + `horizon_bars`) to a `PENDING_OUTCOME` forecast, moving it to `MATURED`. It also compares the query window's current `source_data_hash` against the hash captured at forecast creation; a mismatch (a retroactive provider data revision) sets `data_revision_detected` on the outcome but never mutates the forecast itself. See [prospective-forecast-provenance.md](prospective-forecast-provenance.md) for the full provenance and data-revision contract.

## Evaluation

`create_evaluation_snapshot` scores only `TRUE_PROSPECTIVE` forecasts. Metrics are computed **per horizon**, and each forecast is scored against the historical unconditional base rate for its own instrument/window-length/horizon, **evaluated as-of that forecast's own `data_cutoff_timestamp`** (the data the forecast itself was allowed to know) — a pooled sample can neither compare one horizon's or instrument's forecasts against another's base rate, nor let the baseline see outcomes the forecast did not.

The snapshot's headline scalar fields (`brier_score`, `brier_skill_vs_unconditional`, `log_loss`, `expected_calibration_error`, `direction_accuracy`, `balanced_accuracy`, `mcc`) and the decision both come from the protocol's declared **primary horizon**, which is the horizon the frozen hypothesis is actually about. Every horizon's full metric set, including a paired block-bootstrap confidence interval for `brier_skill_vs_unconditional`, is persisted in `per_horizon_metrics`. The interval is what lets `classify_prospective_decision` reach its `SUPPORTED` branch: it requires the primary-horizon sample to reach `preferred_evidence_matured_forecasts` and `bootstrap_ci_low > 0.0`. The evidence gate counts only primary-horizon matured forecasts — secondary-horizon maturations remain visible in `per_horizon_metrics` but cannot satisfy the primary hypothesis.

This is a measurement-layer concern only: no forecast, probability, context, outcome, or maturation behavior is affected.

## Explicit exclusions

No Market DNA similarity in the primary forecast path. No AI/ML models. No trading, execution, or position-sizing logic. No automatic scheduling -- every iteration is triggered manually via the CLI.

## Market DNA and the shared pipeline

`run-daily`'s incremental derived-state rebuild calls `FeatureBuildService` (Market DNA) alongside window/normalization/context/outcome builds, because all five share the same per-window incremental pipeline architecture from earlier phases. This is acceptable *only* because `historical_probability` and `create_forecast` never read `market_dna` -- they query `pattern_windows`, `market_contexts`, and `outcome_observations` exclusively. Market DNA rows continue to accumulate as a side effect of shared infrastructure, not as an input to the prospective probability, and the operational cost is bounded to the same handful of new rows per instrument per day as every other incremental table (verified live: 6-18 new rows per table per run, never a full rebuild).
