# Forward Path Storage

Forward paths are stored on `OutcomeObservation.forward_path` as JSON. Phase 1 uses `forward_close_log_path_v1`:

- value `0.0` is the anchor point at the source window final close;
- subsequent values are log returns of future closes relative to the anchor close;
- point count is `available_future_bars + 1`;
- `path_hash` is a deterministic SHA-256 hash of the path payload excluding the hash field itself.

Paths are intentionally stored with the outcome row so analogue retrieval can inspect future behavior without recomputing labels from raw bars. The source future bars are still represented by `future_bar_hash` for provenance.
