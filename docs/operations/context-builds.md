# Context builds

Prerequisites:

1. CSV import.
2. Window build.
3. Normalization build.
4. Market DNA feature build.

Example:

```powershell
market-genome context producers
market-genome context dimensions
market-genome context build --producer transparent_context_v1 --feature-set market_dna_v1 --mode incremental
market-genome contexts list
```
