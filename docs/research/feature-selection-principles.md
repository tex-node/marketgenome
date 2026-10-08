# Feature selection principles

Phase 1 features are transparent and auditable.

- Use only bars inside the immutable source window.
- Prefer scale-invariant quantities where possible.
- Separate normalized-path features from raw-return, OHLC, and volume features.
- Keep missing-value behavior explicit instead of imputing silently.
- Version every feature through the feature-set registry.
- Avoid target, outcome, regime, or future information.

Wavelet and learned features are deferred until the persistence, validation, and leakage controls have more coverage.

Context dimensions consume Market DNA features but do not replace them. Context is stored separately so later validation can compare shape-only, context-only, and combined hypotheses.
