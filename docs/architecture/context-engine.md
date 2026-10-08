# Context engine

The Market Context engine is separate from Market DNA.

Market DNA describes the pattern shape. Market Context describes the environment in which that pattern occurred.

The first producer is `transparent_context_v1`. It is rule-based, unsupervised, does not use future outcomes, and depends on verified `MarketDNA`, `NormalizedPattern`, and `PatternWindow` records.

Build modes match earlier pipeline stages: `full`, `incremental`, and `range`.
