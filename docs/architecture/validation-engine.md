# Validation engine

Phase 1 Step 9 adds a research validation layer around analogue retrieval. It does not create trading signals. It evaluates whether historical neighbours explain forward outcomes better than explicit baselines.

Core objects:

- `ExperimentRun`: immutable top-level experiment identity, configuration, dataset hash, code-version metadata, summary, and decision.
- `ExperimentFold`: walk-forward or purged fold boundaries plus exclusion counts.
- `QueryEvaluation`: one query window, horizon, method/baseline, neighbour count, prediction aggregate, actual outcome, and no-lookahead diagnostics.
- `ExperimentMetric`: aggregated metric records with bootstrap metadata.
- `ExperimentArtifact`: generated report payloads.

The service consumes existing `PatternWindow`, `NormalizedPattern`, `MarketDNA`, `MarketContext`, and `OutcomeObservation` records. Query-time retrieval is historical-as-of; outcomes are used only after the prediction aggregate is frozen.

Step 10A diagnostics use the validation result as an input hypothesis: `NO_SUPPORTED_EDGE` triggers representation diagnostics rather than model escalation. Diagnostic runs persist as `diagnostic_v1` experiment runs.

Step 10A.1 adds study manifests above experiments. The study service does not replace walk-forward validation; it coordinates multi-instrument dataset inclusion, episode diversity, preflight gates, pilot/validation/final-test phases, and immutable final-test locks around the existing validation concepts.
