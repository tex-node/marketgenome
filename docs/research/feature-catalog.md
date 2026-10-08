# Feature catalog

`market_dna_v1` is implemented as a deterministic 75-feature handcrafted vector.

Feature groups:

- Path: endpoint return, displacement, length, efficiency, drawdown/runup, endpoint position.
- Trend: linear regression slope/intercept/r-squared/residuals, LSMA endpoint/slope, quadratic curvature.
- Momentum: log-return moments, positive/negative ratios, half-window momentum, autocorrelation, AR(1) coefficient.
- Volatility: realized/upside/downside volatility, ATR normalization, first/second-half expansion, range expansion.
- Distribution: skewness, kurtosis, median, MAD, tails, maximum positive/negative return.
- Persistence and complexity: Hurst R/S, variance ratios, permutation entropy, sample entropy, Higuchi dimension, turning points.
- Swing structure: extrema-derived swing counts, sizes, durations, impulse ratio, higher/lower structural counts.
- Candle geometry: body/range, wick ratios, bullish/bearish/inside/outside bars, close-location value.
- Volume: relative volume, coefficient of variation, trend slope, return correlation, expansion, high-volume location.

Every feature produces either a finite value or an explicit unavailable status. Wavelet features are not part of `market_dna_v1`.

Retrieval diagnostics now calculate per-feature availability, near-constant flags, robust scale estimates, outlier rates, and redundancy clusters. These diagnostics do not automatically drop features.
