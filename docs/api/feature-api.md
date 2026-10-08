# Feature API

Implemented endpoints:

- `GET /api/v1/features/definitions`
- `GET /api/v1/features/sets`
- `GET /api/v1/features/sets/{feature_set_code}`
- `POST /api/v1/features/builds`
- `GET /api/v1/features/builds`
- `GET /api/v1/features/builds/{build_id}`
- `GET /api/v1/market-dna`
- `GET /api/v1/market-dna/{market_dna_id}`
- `GET /api/v1/market-dna/{market_dna_id}/values`
- `GET /api/v1/market-dna/{market_dna_id}/diagnostics`

Feature builds depend on existing normalized patterns that match the feature set's required normalization identity.
