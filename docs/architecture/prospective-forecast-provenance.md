# Prospective Forecast Provenance

Every `ProspectiveForecast` carries a `provenance_class`, validated against an explicit enum (`market_genome_prospective.forecast_analysis.PROVENANCE_CLASSES`): `TRUE_PROSPECTIVE`, `BACKFILL_SIMULATION`, `HISTORICAL_VALIDATION`. `create_forecast` rejects any other value with `UNSUPPORTED_PROVENANCE_CLASS:<value>`. Provenance classes must never be conflated in identity or in evaluation.

## TRUE_PROSPECTIVE

The only class that counts as genuine prospective evidence. Two integrity guards apply only to this class:

1. `forecast_created_at` must be `>= data_cutoff_timestamp` -- a forecast cannot be created before its own data cutoff.
2. No completed `OutcomeObservation` may already exist for the target `pattern_window_id` + `horizon_bars` -- a `TRUE_PROSPECTIVE` forecast can never be created for a timestamp whose future outcome is already known.

Either violation raises `RetroactiveForecastError` with a message prefixed `RETROACTIVE_PROSPECTIVE_FORECAST_REJECTED:`. Callers should match on that literal code, not the full message text.

## BACKFILL_SIMULATION and HISTORICAL_VALIDATION

Exempt from both integrity guards above -- they exist specifically to run the forecasting pipeline against already-known history, for smoke testing, calibration, and methodology validation. They share the forecast/outcome schema but are excluded from `create_evaluation_snapshot`'s primary evaluation query (`provenance_class == "TRUE_PROSPECTIVE"` filter) so they can never leak into the genuinely prospective evidence base.

## Outcome linkage and data revision

`ProspectiveForecastOutcome` references the existing immutable `OutcomeObservation` via `source_forward_outcome_id` (FK) and `source_outcome_hash`, in addition to persisting its own snapshot fields (`actual_return`, `actual_direction`, MFE/MAE, `outcome_hash`). This lets maturation trace back to the exact source row rather than only duplicating its computation.

At maturation, the query window's current `source_data_hash` is compared against the forecast's frozen `source_hash` (captured at creation time) via `detect_data_revision`. A mismatch means the provider retroactively revised history since the forecast was made. This is recorded as `data_revision_detected = True` on the outcome -- the forecast and its original snapshot are never silently rewritten. Interpretation of a revision-flagged forecast (include vs. exclude from primary evaluation) is left to explicit protocol-level policy, not automatic exclusion, since a silent drop would itself be a form of undocumented mutation.
