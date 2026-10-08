# Experiment API

Validation endpoints:

- `GET /api/v1/experiments/definitions`
- `GET /api/v1/validation/methods`
- `GET /api/v1/validation/baselines`
- `GET /api/v1/validation/metrics`
- `GET /api/v1/validation/weighting`
- `POST /api/v1/experiments/runs`
- `GET /api/v1/experiments/runs`
- `GET /api/v1/experiments/runs/{run_id}`
- `GET /api/v1/experiments/runs/{run_id}/folds`
- `GET /api/v1/experiments/runs/{run_id}/evaluations`
- `GET /api/v1/experiments/runs/{run_id}/metrics`
- `GET /api/v1/experiments/runs/{run_id}/report`

Create body:

```json
{
  "configuration": {
    "experiment_code": "walk_forward_analogue_validation_v1",
    "validation_method": "expanding_walk_forward_v1",
    "similarity_method": "market_analogue_v1",
    "outcome_horizons": [1, 3],
    "neighbour_counts": [5, 10],
    "run_nonce": "example"
  }
}
```

