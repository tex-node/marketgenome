# Local development

```powershell
cd C:\MarketGenome
python -m pip install -e ".[dev]"
docker compose up -d postgres redis
python -m alembic -c infrastructure/alembic.ini upgrade head
python -m uvicorn market_genome_api.main:app --app-dir apps/api --reload
```

Run checks:

```powershell
python -m pytest
python -m ruff check .
python -m alembic -c infrastructure/alembic.ini history
docker compose config
market-genome normalization --help
market-genome normalized --help
market-genome features --help
market-genome dna --help
market-genome context --help
market-genome contexts --help
market-genome outcomes --help
market-genome outcome --help
market-genome similarity --help
market-genome validation --help
market-genome experiments --help
market-genome diagnostics --help
market-genome studies --help
market-genome data import-manifest .\research\data\manifests\real_market_data_v1.yaml --dry-run
python .\scripts\verify_postgres_runtime.py
```
