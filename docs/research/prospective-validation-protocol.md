# Prospective Validation Protocol

Frozen protocol `market_context_forecast_v1` (source: [[project-session-log]] Step 10A.4, decision `CONTEXT_SIGNAL_SUPPORTED_DNA_NO_INCREMENTAL_VALUE`). Sources its lineage from the `context_dna_incremental_value_v1` replication protocol and experiment -- a prospective protocol cannot be frozen without that upstream evidence chain resolving first.

## Configuration (frozen, immutable once created)

- Context definition: `trend_volatility`, chosen over `context_family` for explainability despite near-identical Step 10A.4 performance.
- Fallback hierarchy: `trend_volatility -> trend_only -> unconditional`.
- Timeframe: D1. Window lengths: as defined in `MARKET_CONTEXT_FORECAST_V1`.
- Primary horizon: 20 bars. Secondary horizons: 5, 10 bars -- reported for transparency only; neither is promoted to primary regardless of relative performance, since the primary horizon was fixed before any prospective evidence existed.
- Probability method: `raw_frequency_v1` smoothed via `beta_binomial_v1` (Laplace, alpha=beta=1).
- Confidence interval: Wilson score interval.
- Calibration method: `none_v1` -- no post-hoc recalibration unless a compelling, separately-frozen reason is documented.
- Minimum historical sample per fallback level: 30.
- Minimum evidence to interpret results at all: 100 matured `TRUE_PROSPECTIVE` forecasts **at the primary horizon**. Preferred (for a full support/no-support call): 250. Maturations at secondary horizons are reported in `per_horizon_metrics` but never satisfy the primary hypothesis, which is about the primary horizon.
- Instrument universe: the 6 Alpha Vantage FX/crypto instruments carried over from Step 10A.3/10A.4 (equities/metals excluded by the free-tier API key).

## Baseline

Primary baseline is the frozen historical unconditional probability (the `unconditional` fallback level, evaluated as-of each forecast's own cutoff), computed **per row** for that forecast's own instrument, timeframe, window length, and horizon. A single pooled scalar baseline is deliberately not used, since base rates differ across instrument and horizon combinations. An optional trend-only baseline may be added, but only if frozen before prospective forecasting begins -- never fit retroactively against already-observed prospective outcomes.

## Decision logic

`classify_prospective_decision` refuses any interpretation below the minimum-evidence threshold (`PROSPECTIVE_EVIDENCE_ACCUMULATING`). Above it, a non-positive Brier skill vs. unconditional yields `PROSPECTIVE_CONTEXT_SIGNAL_NOT_SUPPORTED`; a positive skill below the preferred-evidence threshold or without a bootstrap CI clearly excluding zero yields `PROSPECTIVE_CONTEXT_SIGNAL_WEAK`; only preferred-evidence-or-more matured forecasts with positive skill and a CI excluding zero yield `PROSPECTIVE_CONTEXT_SIGNAL_SUPPORTED`. The evidence count, the Brier skill, and the bootstrap interval are all taken from the **primary horizon**; the interval is a paired block-bootstrap over that horizon's matured forecasts.

## Evaluation metrics

Brier score, Brier skill vs. unconditional, log loss, expected calibration error (10-bin), direction accuracy, balanced accuracy, and MCC (Matthews correlation coefficient) -- computed only over `TRUE_PROSPECTIVE`, `MATURED` forecasts, **separately per horizon**. The headline snapshot fields report the primary horizon; all horizons are retained in `per_horizon_metrics` with their own paired block-bootstrap interval. Balanced accuracy and MCC are `None` (not zero) when a class is entirely absent from a horizon's matured sample, since both are undefined rather than degenerate in that case.

## Explicit scope limits

No Market DNA in the primary forecast. No AI/ML model. No trading, execution, position sizing, or risk management. No automatic scheduling of daily iterations.
