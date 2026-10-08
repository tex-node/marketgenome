# Outcome Limitations

Forward outcomes are historical labels. They are not forecasts, signals, fills, or executable trading results.

Known limitations in Phase 1:

- no bid/ask spread, slippage, liquidity, or execution modeling;
- no intrabar ordering when high and low both cross barriers in the same bar;
- no market-session calendar handling beyond existing bar timestamps;
- partial horizons are useful for data availability but should be filtered out for final supervised validation unless explicitly studied.
