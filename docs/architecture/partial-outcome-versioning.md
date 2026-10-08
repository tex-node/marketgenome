# Partial Outcome Versioning

When fewer than the requested horizon bars are available, the engine persists a partial observation instead of dropping it. Partial rows carry:

- `is_complete = false`;
- `available_future_bars`;
- `PARTIAL_HORIZON` and optionally `NO_FUTURE_BARS` quality flags;
- hashes over the future bars actually available.

If later data makes the same window/horizon complete, the complete observation is inserted as a new immutable row. `supersedes_observation_id` points to the latest matching partial row when available.
