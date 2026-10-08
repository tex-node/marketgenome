# Walk-forward validation

The validation engine supports:

- `expanding_walk_forward_v1`: index history expands; test windows move forward.
- `rolling_walk_forward_v1`: index history uses the most recent configured count.
- `anchored_holdout_v1`: one anchored split.
- `purged_kfold_v1`: k-fold-style test slices with purged candidate eligibility.

Each fold stores index and test bounds. Candidate-level filtering still applies inside the fold so a candidate must end before the query, pass purge/embargo checks, and have complete forward outcomes when `complete_outcomes_only` is enabled.

