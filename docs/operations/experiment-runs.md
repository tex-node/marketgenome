# Experiment runs

Experiment execution is implemented through the validation engine.

Typical local flow:

```powershell
market-genome validation methods
market-genome validation baselines
market-genome experiments definitions
market-genome experiments create .\research\experiments\baseline_market_analogue.yaml
market-genome experiments list
market-genome experiments inspect <experiment_run_id>
market-genome experiments metrics <experiment_run_id>
market-genome experiments report <experiment_run_id>
```

Runs persist immutable configuration, dataset hash, code-version metadata, fold definitions, query evaluations, metrics, and markdown report artifacts.
