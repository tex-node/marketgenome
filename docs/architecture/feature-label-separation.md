# Feature and Label Separation

Market Genome treats future outcomes as labels. They are never inputs to:

- window generation;
- normalization and resampling;
- Market DNA feature extraction;
- transparent Market Context classification.

The outcome build verifies the source window hash before labeling. Tests assert that outcome builds do not mutate `NormalizedPattern.representation_hash`, `MarketDNA.feature_vector_hash`, or `MarketContext.context_hash`.

This separation is required to avoid lookahead leakage in later analogue retrieval and validation phases.
