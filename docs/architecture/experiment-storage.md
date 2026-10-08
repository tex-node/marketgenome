# Experiment storage

Experiment records are append-only. Runs are keyed by experiment code/version, dataset hash, configuration hash, and run nonce. Folds, query evaluations, metrics, and artifacts reference the run.

Hashes stored by the engine:

- dataset hash: selected windows, source hashes, outcome set, horizons, and quality filters;
- configuration hash: canonical experiment configuration;
- fold hash: validation method, fold number, time bounds, and configuration;
- evaluation hash: query, ranked candidate ids, method/baseline, aggregate prediction, and actual-outcome hash;
- metric hash: run, horizon, method, metric code, value, and sample count.

