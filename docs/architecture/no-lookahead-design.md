# No-lookahead design

Market Genome separates market-state features from future outcomes.

Rules:

- Feature functions receive only bars inside the pattern window.
- Normalization uses only window-local values or indicators known at the window end.
- Outcome calculations are persisted separately.
- Historical simulation indices must include only data available before the query timestamp.
- Validation must purge overlapping outcomes and apply temporal embargo where configured.

Current window-engine tests prove:

- Appending future bars creates only new windows.
- Existing window boundaries and source hashes are unchanged by future bars.
- Changing a bar inside a window changes that window source hash.
- Changing a bar after a window end does not change that window source hash.

Current normalization tests prove:

- Source-window hashes are recalculated before normalization.
- ATR uses only bars inside the immutable pattern window.
- Z-score and volatility scaling use only values inside the pattern window.
- Appending/changing future bars outside a window does not mutate existing normalized values.

Current feature-engine tests prove:

- Market DNA depends on immutable source-window and normalized-representation hashes.
- Feature extraction uses only the referenced pattern window and normalized pattern.
- Scaling raw OHLC prices does not change core scale-invariant feature values.

Current context-engine tests prove:

- Market Context depends on verified source-window, representation, and feature-vector hashes.
- Multi-resolution context links only same-end-timestamp records.
- Missing volume remains unavailable activity rather than being imputed from price.

Current outcome-engine tests prove:

- Future bars are strictly after the pattern window end.
- The anchor bar is excluded from future horizons.
- Outcome builds do not mutate normalized patterns, Market DNA, or Market Context.
- Partial future horizons are explicitly flagged rather than silently treated as complete.

Current similarity-engine tests prove:

- Similarity methods declare that they do not use future outcomes.
- Historical-only searches exclude the query window and candidate windows ending after the query.
- Similarity-match diagnostics record `uses_future_outcomes = false`.

Current validation-engine tests prove:

- Candidate eligibility rejects future/contemporary candidates, self matches, source overlap, outcome overlap, embargo violations, and configured same/cross-asset exclusions.
- Query evaluations record `historical_as_of = true` and `uses_query_actual_outcome_for_forecast = false`.
- Fold generation is deterministic for ordered and reversed input windows.

Current diagnostic-engine tests prove:

- Refined similarity methods declare `uses_future_outcomes = false`.
- Distance/outcome diagnostics join query outcomes only after ranking.
- Availability-aware distance tests preserve symmetry and prevent missing features from improving penalized similarity.
