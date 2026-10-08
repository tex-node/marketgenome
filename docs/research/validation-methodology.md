# Validation methodology

Use walk-forward validation with time-ordered splits. Do not use random train/test splits for overlapping market windows.

Validation requirements:

- Purge overlapping windows and outcomes.
- Apply embargo periods.
- Track immutable experiment configuration.
- Report confidence intervals and sample sizes.
- Segment results by asset, timeframe, regime, and date range.

The current window catalog supports later validation by preserving immutable window boundaries, source hashes, build configuration hashes, quality flags, and exact source-bar retrieval.

Normalized pattern records add versioned normalization configuration and representation hashes so later experiments can compare methods reproducibly.

Market DNA records add deterministic feature-vector hashes and explicit availability masks. Predictive validation of those features belongs to later outcome/regime experiments.

Market Context records add descriptive environment labels and confidence scores. They remain separate from future outcome labels.

Forward Outcome observations add deterministic labels for later supervised validation. Validation should normally filter to `is_complete = true` and should segment by horizon to avoid mixing materially different label definitions.

Similarity queries add persisted retrieval sets. Validation evaluates retrieved analogue sets against forward outcomes after retrieval, with purging and embargo applied to overlapping windows.

Step 9 implements this as persisted experiment runs with walk-forward, rolling, purged-k-fold, and anchored-holdout methods. Every query evaluation records the candidate ids, prediction aggregate, actual outcome, and diagnostics proving historical-as-of retrieval.

Step 10A adds a diagnostic stage before any new model class is considered. It asks whether the representation, distance, feature scale, feature availability, context weighting, or episode concentration explain validation failure.
