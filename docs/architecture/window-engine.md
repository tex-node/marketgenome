# Window engine

The Phase 1 Step 3 window engine creates immutable `PatternWindow` records from persisted `PriceBar` rows.

For ordered bars `b[0] ... b[n-1]`, a window of length `L` ending at index `i` is:

```text
b[i-L+1 : i+1]
```

With `stride = 1`, every eligible endpoint is used. With larger stride values, endpoints are skipped deterministically.

## Hashing

Each window stores `source_data_hash`, a SHA-256 hash over canonical JSON containing ordered `timestamp`, OHLCV, `instrument_id`, and `timeframe_id`.

Policy:

- Timestamps are serialized in UTC ISO-8601.
- Numeric values use deterministic string formatting.
- Volume is included; null volume is serialized as null and flagged.
- Bar ordering is part of the hash.

`build_configuration_hash` is a SHA-256 hash over canonical JSON for lengths, stride, mode, version, date range, quality policy, instrument, and timeframe. Dictionary key order does not change the hash.

## Idempotency

Windows are unique by instrument, timeframe, end timestamp, length, version, and source hash. Re-running the same build does not create duplicates. If source bars change, the source hash changes and a new immutable window can be produced.

## Calendar limitations

The current implementation supports `continuous`, `session_based`, and `unknown` calendar modes. It does not yet implement exchange calendars. Unknown calendars are flagged rather than treated as perfectly complete.

