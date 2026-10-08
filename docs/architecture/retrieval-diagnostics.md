# Retrieval diagnostics

Step 10A adds a bounded diagnostic layer for explaining analogue retrieval failures. It is explicitly diagnostic, not a trading or signal engine.

The diagnostic service creates a normal `ExperimentRun` with version `diagnostic_v1`, then persists immutable `DiagnosticArtifact` records for:

- feature distributions;
- redundancy/correlation structure;
- distance/outcome monotonicity;
- episode concentration;
- window/horizon alignment;
- markdown diagnostic report.

Large all-pairs diagnostics are capped by configuration (`maximum_records`, `maximum_pairs`) to avoid unbounded matrix generation.

