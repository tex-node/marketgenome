# Window generation

Seed/import data first, then build windows.

```powershell
market-genome windows build `
  --symbol BTCUSDT `
  --exchange BINANCE `
  --timeframe H1 `
  --lengths 16,32,64 `
  --stride 1 `
  --mode incremental
```

Modes:

- `full`: evaluate the selected date range from scratch without deleting existing windows.
- `incremental`: start after the latest existing window end for each length/version.
- `range`: evaluate only the provided date range.

Quality policy is currently service/API-configurable. The CLI uses strict continuous-market policy by default.

