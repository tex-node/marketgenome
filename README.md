# Market Genome

Market Genome is a research platform for market-pattern indexing, analogue retrieval, and statistically defensible forward-outcome analysis.

Current Phase 1 capabilities include foundation services, registry inspection, CSV OHLCV import with audit records, immutable sliding-window generation, normalization/resampling, deterministic Market DNA feature extraction, transparent Market Context classification, versioned Forward Outcome observations, historical analogue retrieval, walk-forward validation with baselines, retrieval diagnostics with transparent refined similarity methods, a bounded multi-asset diagnostic study layer with episode-diversity controls and final-test locking, cross-provider independent replication, and a genuinely prospective (forward-looking) Market Context forecasting and evaluation system.

Yahoo Finance support is available only through the optional `yahoo` extra and is classified as `PILOT_AND_RESEARCH_SOURCE`. Yahoo-backed studies are `PILOT_ONLY` until independently replicated with another data source.

Intended production URL: `https://genome.fothlog.com`

## Local start

```powershell
cd C:\MarketGenome
python -m pip install -e ".[dev]"
# optional provider support:
python -m pip install -e ".[dev,yahoo]"
docker compose up -d postgres redis
python -m alembic -c infrastructure/alembic.ini upgrade head
market-genome registry seed-timeframes

market-genome data import-csv .\tests\fixtures\sample_ohlcv.csv `
  --symbol BTCUSDT `
  --name "Bitcoin / Tether" `
  --asset-class crypto `
  --exchange BINANCE `
  --currency USDT `
  --timezone UTC `
  --timeframe H1 `
  --timeframe-seconds 3600 `
  --source BINANCE_CSV

market-genome windows build `
  --symbol BTCUSDT `
  --exchange BINANCE `
  --timeframe H1 `
  --lengths 8,16 `
  --stride 1 `
  --mode incremental

market-genome normalization build `
  --method anchored_log_return `
  --points 64 `
  --resampling linear `
  --mode incremental `
  --window-version window_v1 `
  --normalization-version normalization_v1

market-genome features build `
  --feature-set market_dna_v1 `
  --mode incremental

market-genome context build `
  --producer transparent_context_v1 `
  --feature-set market_dna_v1 `
  --mode incremental

market-genome outcomes build `
  --outcome-set forward_outcomes_v1 `
  --horizons 1,3,5,10,20 `
  --mode incremental

market-genome similarity search <window_id> `
  --method market_analogue_v1 `
  --top-k 20

market-genome experiments create .\research\experiments\baseline_market_analogue.yaml

market-genome diagnostics run .\research\experiments\representation_diagnostic.yaml

market-genome data import-manifest .\research\data\manifests\real_market_data_v1.yaml --dry-run
market-genome data import-manifest .\research\data\manifests\real_market_data_v1.yaml
market-genome data quality-report --manifest real_market_data_v1
market-genome data providers
market-genome data fetch-yahoo .\research\data\manifests\yahoo_market_data_pilot_v1.yaml --dry-run
market-genome data provider-smoke yahoo_finance_v1 --symbol SPY
market-genome studies create .\research\studies\multi_asset_episode_study_v1.yaml
market-genome studies create .\research\studies\real_multi_asset_episode_study_v1.yaml
market-genome studies create .\research\studies\yahoo_multi_asset_pilot_v1.yaml
market-genome studies prepare-data <study_id> --batch-size 1
market-genome studies status <study_id>
market-genome studies preflight <study_id>
market-genome studies run-pilot <study_id>
market-genome studies run-validation <study_id>
market-genome studies lock-final-test <study_id>
market-genome studies report <study_id>

python -m uvicorn market_genome_api.main:app --app-dir apps/api --reload
```

Health checks:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/ready
```

Run tests:

```powershell
python -m pytest
python -m ruff check .
```

## CSV format

Required columns:

```text
timestamp,open,high,low,close,volume
```

Optional columns:

```text
symbol,timeframe,source,spread,bid,ask,trade_count,open_interest
```

Phase 1 intentionally does not include trading execution, predictive claims, or learned embeddings.

## API highlights

- `POST /api/v1/data/imports/csv`
- `GET /api/v1/data/imports`
- `GET /api/v1/data/imports/{import_id}/issues`
- `GET /api/v1/instruments`
- `GET /api/v1/timeframes`
- `GET /api/v1/data-sources`
- `POST /api/v1/windows/builds`
- `GET /api/v1/windows`
- `GET /api/v1/windows/{window_id}/bars`
- `GET /api/v1/normalization/methods`
- `POST /api/v1/normalization/builds`
- `GET /api/v1/normalized-patterns/{normalized_pattern_id}/values`
- `GET /api/v1/features/definitions`
- `POST /api/v1/features/builds`
- `GET /api/v1/market-dna/{market_dna_id}/values`
- `GET /api/v1/context/producers`
- `POST /api/v1/context/builds`
- `GET /api/v1/market-contexts/{market_context_id}/explanation`
- `GET /api/v1/outcomes/definitions`
- `POST /api/v1/outcomes/builds`
- `GET /api/v1/outcome-observations/{outcome_id}/path`
- `GET /api/v1/windows/{window_id}/outcomes`
- `GET /api/v1/similarity/methods`
- `GET /api/v1/experiments/definitions`
- `POST /api/v1/experiments/runs`
- `GET /api/v1/experiments/runs/{run_id}/report`
- `GET /api/v1/diagnostics/definitions`
- `POST /api/v1/diagnostics/experiments`
- `GET /api/v1/diagnostics/experiments/{experiment_id}/report`
- `GET /api/v1/studies/definitions`
- `POST /api/v1/studies`
- `GET /api/v1/studies/{study_id}/preflight`
- `POST /api/v1/studies/{study_id}/run-pilot`
- `POST /api/v1/studies/{study_id}/run-validation`
- `POST /api/v1/studies/{study_id}/lock-final-test`
- `GET /api/v1/studies/{study_id}/report`
- `POST /api/v1/similarity/search`
- `GET /api/v1/similarity/queries/{query_id}/matches`
- `GET /api/v1/windows/{window_id}/similar`
- `GET /api/v1/prospective/protocols`
- `GET /api/v1/prospective/forecasts`
- `GET /api/v1/prospective/latest`
- `GET /api/v1/prospective/evaluation`

## CLI highlights

```powershell
market-genome --help
market-genome db status
market-genome db upgrade
market-genome registry seed-timeframes
market-genome instruments list
market-genome timeframes list
market-genome sources list
market-genome data imports
market-genome data import-manifest .\research\data\manifests\real_market_data_v1.yaml --dry-run
market-genome data quality-report --manifest real_market_data_v1
market-genome data providers
market-genome data fetch-yahoo .\research\data\manifests\yahoo_market_data_pilot_v1.yaml --dry-run
market-genome windows list
market-genome normalization methods
market-genome normalized list
market-genome features definitions
market-genome dna list
market-genome context producers
market-genome contexts list
market-genome outcomes definitions
market-genome outcomes build --outcome-set forward_outcomes_v1 --horizons 1,3,5,10 --mode incremental
market-genome outcome list
market-genome similarity methods
market-genome similarity search <window_id> --top-k 20
market-genome diagnostics definitions
market-genome diagnostics run .\research\experiments\representation_diagnostic.yaml
market-genome studies definitions
market-genome studies create .\research\studies\multi_asset_episode_study_v1.yaml
market-genome studies status <study_id>
market-genome studies prepare-data <study_id>
market-genome studies report <study_id>
market-genome prospective protocols
market-genome prospective create-protocol --protocol market_context_forecast_v1
market-genome prospective run-daily --dry-run
market-genome prospective forecast-only --dry-run
market-genome prospective mature
market-genome prospective evaluate
market-genome prospective status
```

Prospective forecasting is never scheduled automatically; every `run-daily` iteration is triggered manually. See [docs/architecture/prospective-context-forecasting.md](docs/architecture/prospective-context-forecasting.md) and [docs/operations/prospective-daily-run.md](docs/operations/prospective-daily-run.md).
