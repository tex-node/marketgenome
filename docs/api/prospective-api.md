# Prospective API

Read-only endpoints over the prospective forecasting system. No endpoint creates, mutates, or matures a forecast -- all writes happen through the CLI.

Core endpoints:

- `GET /api/v1/prospective/protocols`
- `GET /api/v1/prospective/forecasts`
- `GET /api/v1/prospective/forecasts/{forecast_id}`
- `GET /api/v1/prospective/latest`
- `GET /api/v1/prospective/evaluation`

Forecast list filters include protocol and instrument. `latest` orders by `forecast_created_at` descending and accepts a `limit`.

`ProspectiveForecastResponse` exposes a probability estimate from historical context matching (`probability_positive`, `probability_negative`, confidence bounds, sample counts, fallback level used) explicitly framed as a research signal, not a trade recommendation. No endpoint or response field uses buy/sell/long/short/entry/exit language.

`ProspectiveEvaluationSnapshotResponse` exposes `brier_score`, `brier_skill_vs_unconditional`, `log_loss`, `expected_calibration_error`, `direction_accuracy`, `balanced_accuracy`, `mcc`, `forecast_count`, `matured_count`, and the protocol's current decision status. It also exposes `primary_horizon`, `primary_horizon_matured_count`, `bootstrap_ci_low`, `bootstrap_ci_high`, and `per_horizon_metrics`: the scalar metric fields are the **primary horizon's** metrics (the horizon the frozen hypothesis is about), while `per_horizon_metrics` maps every horizon (`"5"`, `"10"`, `"20"`) to its own full metric set and paired block-bootstrap interval.
