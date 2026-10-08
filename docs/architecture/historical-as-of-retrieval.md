# Historical-as-of retrieval

Validation uses only candidate windows with `candidate.end_timestamp < query.end_timestamp`. Query actual outcomes are loaded after the prediction aggregate is built and are recorded as actuals, not inputs.

Every query evaluation stores diagnostics:

- `historical_as_of: true`
- `uses_query_actual_outcome_for_forecast: false`
- ranked candidate ids

This complements the similarity engine's own historical-only policy with validation-specific purge and embargo controls.

