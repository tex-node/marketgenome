# Feature builds

Typical local sequence:

```powershell
market-genome features definitions
market-genome features sets
market-genome features set-show market_dna_v1
market-genome features build --feature-set market_dna_v1 --mode incremental
market-genome features builds
market-genome dna list
```

Prerequisites:

1. Import OHLCV data.
2. Build pattern windows.
3. Build normalized patterns using `anchored_log_return`, `normalization_v1`, `linear`, and 64 points.

The build service verifies hashes before extracting features.
