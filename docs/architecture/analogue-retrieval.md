# Analogue Retrieval

Analogue retrieval starts from a query `PatternWindow`. The service resolves its normalized representation, Market DNA vector, and Market Context when available.

Candidate windows are filtered by:

- same window length by default;
- optional instrument, timeframe, and window-length filters;
- temporal policy.

The default temporal policy is `historical_only`, which permits only candidate windows ending before the query window end timestamp. This prevents retrieving future examples for a historical query.

Retrieval diagnostics can additionally measure episode concentration and apply a maximum-matches-per-episode cap during diagnostic ranking. This is used to detect near-duplicate historical episodes that may overstate neighbour diversity.
