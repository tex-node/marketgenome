# Window API

Build windows:

```text
POST /api/v1/windows/builds
```

Example body:

```json
{
  "instrument_id": "uuid",
  "timeframe_id": "uuid",
  "window_lengths": [16, 32, 64],
  "stride": 1,
  "mode": "incremental",
  "window_version": "window_v1",
  "quality_policy": {
    "mode": "strict",
    "maximum_missing_bars": 0,
    "maximum_gap_ratio": 0.0,
    "calendar_mode": "continuous"
  }
}
```

Inspect:

```text
GET /api/v1/windows/builds
GET /api/v1/windows/builds/{build_id}
GET /api/v1/windows
GET /api/v1/windows/{window_id}
GET /api/v1/windows/{window_id}/bars
```

The bars endpoint returns the exact ordered source bars used by the window.

