# Outcome Builds

CLI examples:

```powershell
market-genome outcomes definitions
market-genome outcomes sets
market-genome outcomes set-show forward_outcomes_v1
market-genome outcomes build --outcome-set forward_outcomes_v1 --horizons 1,3,5,10 --mode incremental
market-genome outcomes builds
market-genome outcome list
market-genome outcome inspect <outcome_id>
market-genome outcome values <outcome_id>
market-genome outcome path <outcome_id>
market-genome outcome barriers <outcome_id>
market-genome outcome diagnostics <outcome_id>
market-genome windows outcomes <window_id>
```

Operational rule: run outcome builds after window generation, and after any optional normalization/feature/context builds if you are validating feature-label separation in the same pipeline.
