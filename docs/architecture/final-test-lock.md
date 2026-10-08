# Final-test lock

Final-test execution requires a persisted lock containing:

- selected method;
- selected baselines;
- primary metrics;
- window lengths;
- outcome horizons;
- neighbour counts;
- episode cap;
- context rules;
- scaling method.

The lock is hashed. Re-running lock creation with the same study is idempotent. Changing the locked design requires a new study version.

