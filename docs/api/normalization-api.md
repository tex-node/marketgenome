# Normalization API

Methods:

```text
GET /api/v1/normalization/methods
```

Build:

```text
POST /api/v1/normalization/builds
GET /api/v1/normalization/builds
GET /api/v1/normalization/builds/{build_id}
```

Inspect:

```text
GET /api/v1/normalized-patterns
GET /api/v1/normalized-patterns/{normalized_pattern_id}
GET /api/v1/normalized-patterns/{normalized_pattern_id}/values
GET /api/v1/normalized-patterns/{normalized_pattern_id}/diagnostics
```

Example build body:

```json
{
  "normalization_method": "anchored_log_return",
  "normalization_version": "normalization_v1",
  "resampling_method": "linear",
  "resample_points": 64,
  "mode": "incremental",
  "source_window_version": "window_v1"
}
```

