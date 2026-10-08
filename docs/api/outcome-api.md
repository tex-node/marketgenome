# Outcome API

Core endpoints:

- `GET /api/v1/outcomes/definitions`
- `GET /api/v1/outcomes/sets`
- `GET /api/v1/outcomes/sets/{outcome_set_code}`
- `POST /api/v1/outcomes/builds`
- `GET /api/v1/outcomes/builds`
- `GET /api/v1/outcomes/builds/{build_id}`
- `GET /api/v1/outcome-observations`
- `GET /api/v1/outcome-observations/{outcome_id}`
- `GET /api/v1/outcome-observations/{outcome_id}/values`
- `GET /api/v1/outcome-observations/{outcome_id}/path`
- `GET /api/v1/outcome-observations/{outcome_id}/barriers`
- `GET /api/v1/outcome-observations/{outcome_id}/diagnostics`
- `GET /api/v1/windows/{window_id}/outcomes`

Observation list filters include instrument, timeframe, window length, horizon, completion state, direction class, continuation/reversal class, first barrier hit, and quality flag.
