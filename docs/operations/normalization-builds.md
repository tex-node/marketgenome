# Normalization builds

Example:

```powershell
market-genome normalization build `
  --method anchored_log_return `
  --points 64 `
  --resampling linear `
  --mode incremental `
  --window-version window_v1 `
  --normalization-version normalization_v1
```

Inspect:

```powershell
market-genome normalization methods
market-genome normalization builds
market-genome normalized list
market-genome normalized inspect NORMALIZED_PATTERN_ID
market-genome normalized values NORMALIZED_PATTERN_ID
```

