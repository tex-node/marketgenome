# Forward Outcome Engine

The Forward Outcome Engine labels completed `PatternWindow` rows with strictly future price behavior. It is a downstream research-label layer, not an input to normalization, Market DNA, or Market Context.

`forward_outcomes_v1` anchors every calculation at the source window final close and only consumes `PriceBar` rows whose timestamp is greater than `PatternWindow.end_timestamp`.

Persisted objects:

- `OutcomeBuild`: immutable build audit record with requested horizons, filters, configuration hash, counters, status, and elapsed time.
- `OutcomeObservation`: one pattern-window/outcome-set/horizon observation with scalar outcomes, normalized forward path, barrier results, diagnostics, quality flags, hashes, and partial-completion state.

The engine supports full, incremental, and range-filtered builds. Existing observations are not overwritten; reruns either reuse existing rows or create new versioned rows when future data, source hashes, or configuration hashes change.
