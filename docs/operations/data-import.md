# Data import

CSV ingestion validates required OHLCV fields, normalizes timestamps to UTC, records a SHA-256 source hash, and rejects invalid rows.

The importer is available through service code, FastAPI, and CLI.

```powershell
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
```

Dry runs validate and persist an audit record without inserting bars.
