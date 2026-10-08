# Data flow

Initial data flow:

```text
CSV file
→ schema and row validation
→ source hash generation
→ instrument/timeframe/source registry upsert
→ validated OHLCV rows
→ price_bars persistence
→ import report
→ window build request
→ immutable pattern_windows
→ exact source-bar inspection
→ normalized_patterns
→ normalized value/diagnostic inspection
```

Validation rejects invalid timestamps, duplicate timestamps, out-of-order rows, non-finite values, non-positive prices, negative volume, and invalid OHLC relationships. Timestamp parsing normalizes to UTC.

Import runs are persisted in `data_imports`; row issues are persisted in `data_import_issues`.

Market DNA feature vectors are the next persisted artifact after `normalized_patterns`. Each row depends on both the source-window hash and normalized-representation hash.

Market Context records are produced after Market DNA and depend on source-window, normalized-representation, and feature-vector hashes.

Forward Outcome observations are produced after immutable windows and depend on source-window hash verification plus strictly future bars. They are labels for later validation and analogue analysis, not inputs to Market DNA or Market Context.

Similarity queries consume normalized patterns, Market DNA, and Market Context records to retrieve historical analogue windows. Forward outcomes are excluded from similarity scoring and can be joined only after retrieval for evaluation.

Validation experiments consume windows, contexts, analogue rankings, baselines, and completed outcomes. They persist folds, query evaluations, metrics, and report artifacts without mutating upstream research artifacts.
