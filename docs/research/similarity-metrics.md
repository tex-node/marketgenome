# Similarity Metrics

Implemented Phase 1 methods:

- `shape_euclidean_v1`: Euclidean distance between normalized close paths.
- `shape_correlation_v1`: `1 - correlation` between normalized close paths.
- `dna_cosine_v1`: cosine distance over commonly available Market DNA features.
- `market_analogue_v1`: weighted blend of path distance, DNA cosine distance, and context distance.

All methods declare `uses_future_outcomes = false`.
