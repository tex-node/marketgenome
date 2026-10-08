# Similarity methods

Planned initial methods:

- Resampled shape distance.
- Correlation distance.
- Cosine similarity.
- Dynamic Time Warping.
- Market DNA feature-vector distance.
- Regime compatibility scoring.

Weights are configuration parameters, not evidence of truth.

Step 8 adds initial historical analogue retrieval with path, Market DNA, and context-based metrics. Vector indexing remains unimplemented; searches are exact in-process scans over persisted rows.

Step 9 validates similarity methods against explicit baselines through walk-forward experiments. Similarity scores are treated as retrieval evidence only; skill must be demonstrated through out-of-sample outcome metrics.

Step 10A adds refined transparent methods for diagnosis:

- `dna_robust_cosine_v1`;
- `dna_robust_euclidean_v1`;
- `dna_group_balanced_v1`;
- `shape_dna_context_v2`.

These methods do not use future outcomes and remain comparable with Step 8 methods.
