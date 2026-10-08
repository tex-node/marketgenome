# Feature engine

The Phase 1 feature engine converts verified normalized pattern representations into persisted `MarketDNA` rows.

The implemented feature set is `market_dna_v1`, a deterministic 75-feature handcrafted vector. It uses normalized close values from `anchored_log_return` / `normalization_v1` / `linear` / 64 points, plus raw OHLCV bars constrained to the exact immutable `PatternWindow` boundary.

The service rejects source-window hash drift and source-representation hash drift before writing Market DNA. This preserves the no-lookahead and immutability guarantees from the window and normalization layers.

The engine supports `full`, `incremental`, and `range` selection modes. Unavailable features are stored as `null` with an explicit availability reason.
