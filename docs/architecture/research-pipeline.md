# Research pipeline

Phase 1 now progresses from validated bars to immutable sliding windows, normalized/resampled pattern representations, Market DNA feature vectors, transparent Market Context records, versioned Forward Outcome observations, historical analogue retrieval, walk-forward validation with baselines, retrieval diagnostics, and bounded multi-asset diagnostic studies.

Guardrails:

- Features must use only data available at the window end.
- Outcomes must be stored separately from retrieval features.
- Overlapping time-series samples require purging/embargo in validation.
- Negative experiment results are first-class outputs.

The current similarity layer retrieves historical candidates using only contemporaneous feature/context data. Outcomes remain post-retrieval labels and are joined only by the validation engine after prediction aggregates have been produced.

The diagnostic layer analyzes feature scale, availability, redundancy, distance/outcome monotonicity, episode concentration, and window/horizon alignment before any escalation to more complex modelling is considered.

The study layer formalizes real multi-asset readiness. A `StudyManifest` binds a universe, windows, horizons, retrieval arms, baseline arms, quality gates, dataset hash, and optional final-test lock. Final-test execution is intentionally separate from pilot and validation execution so the selected configuration is committed before held-out evaluation.
