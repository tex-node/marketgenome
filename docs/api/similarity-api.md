# Similarity API

Core endpoints:

- `GET /api/v1/similarity/methods`
- `GET /api/v1/similarity/methods/{method_code}`
- `POST /api/v1/similarity/search`
- `GET /api/v1/similarity/queries`
- `GET /api/v1/similarity/queries/{query_id}`
- `GET /api/v1/similarity/queries/{query_id}/matches`
- `GET /api/v1/windows/{window_id}/similar`

Default search behavior uses `market_analogue_v1`, `top_k = 20`, and `temporal_policy = historical_only`.
