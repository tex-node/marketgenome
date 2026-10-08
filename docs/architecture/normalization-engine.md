# Normalization engine

The normalization engine converts immutable `PatternWindow` records into immutable `NormalizedPattern` records.

Flow:

```text
PatternWindow
→ exact ordered bars
→ source hash verification
→ method-specific normalization
→ fixed-point resampling
→ diagnostics
→ representation hash
→ persisted NormalizedPattern
```

The method registry is code-based instead of database-backed in `normalization_v1`. This keeps formulas version-controlled with tests and avoids mutable production method definitions. Builds persist the method code, version, configuration, and deterministic configuration hash.

Representations are stored as JSON for Phase 1 to preserve SQLite test compatibility and easy inspection. Later phases may add compact binary or columnar storage if performance requires it.

Idempotency key:

```text
pattern_window_id
normalization_method
normalization_version
resampling_method
resample_points
configuration_hash
source_window_hash
```

Build `mode` is intentionally excluded from representation identity because it controls selection behavior, not output semantics.

