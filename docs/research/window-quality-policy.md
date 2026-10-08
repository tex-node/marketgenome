# Window quality policy

Current flags:

- `NONE`
- `MISSING_BARS`
- `DUPLICATE_TIMESTAMPS`
- `NON_MONOTONIC_TIMESTAMPS`
- `NULL_VOLUME`
- `ZERO_VOLUME`
- `EXTREME_GAP`
- `INVALID_OHLC`
- `SOURCE_DATA_CHANGED`
- `INSUFFICIENT_BARS`
- `UNKNOWN_CALENDAR`

Strict mode rejects missing/extreme gaps for continuous fixed-duration timeframes. `allow_gaps` persists windows with flags for later filtering. Exchange calendars are intentionally not implemented in this phase.

