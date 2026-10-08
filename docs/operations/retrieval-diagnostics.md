# Retrieval diagnostics operations

Run a bounded diagnostic:

```powershell
market-genome diagnostics run .\research\experiments\representation_diagnostic.yaml
market-genome diagnostics list
market-genome diagnostics inspect <experiment_id>
market-genome diagnostics report <experiment_id>
```

Useful inspection commands:

```powershell
market-genome diagnostics definitions
market-genome diagnostics scaling-methods
market-genome diagnostics availability-policies
market-genome diagnostics feature-distributions <experiment_id>
market-genome diagnostics redundancy <experiment_id>
market-genome diagnostics distance-outcome <experiment_id>
market-genome diagnostics episodes <experiment_id>
```

