# Similarity Engine

The Similarity Engine retrieves historical analogue windows without using future outcomes.

Phase 1 Step 8 adds:

- a versioned similarity method registry;
- persisted `SimilarityQuery` records;
- persisted `SimilarityMatch` rows with rank, distance, score, component scores, hashes, diagnostics, and quality flags;
- a historical-only default temporal policy.

The default method, `market_analogue_v1`, blends normalized path distance, Market DNA cosine distance, and transparent Market Context compatibility.

Step 10A adds transparent refined methods without replacing existing methods:

- `dna_robust_cosine_v1`;
- `dna_robust_euclidean_v1`;
- `dna_group_balanced_v1`;
- `shape_dna_context_v2`.

These methods add availability coverage diagnostics, robust feature compression, group-balanced contribution, and explicit score decomposition.
