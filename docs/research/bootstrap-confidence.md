# Bootstrap confidence

Metric confidence intervals use deterministic bootstrap resampling. Seeds are derived from canonical hashes of run id, horizon, method, and metric code.

The current implementation stores percentile interval bounds and standard error. This is suitable for repeatable local research runs, not formal inference on its own.

