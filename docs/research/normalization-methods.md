# Normalization methods

Version: `normalization_v1`

## anchored_simple_return

Formula: `close_t / close_0 - 1`.

Retains direction and percentage amplitude. Removes absolute price scale. Rejects zero/non-positive invalid anchors.

## anchored_log_return

Formula: `log(close_t / close_0)`.

Recommended baseline for close-path research, pending validation. Removes absolute price scale and preserves direction.

## anchored_ohlc

Formula: `open/high/low/close / close_0 - 1`.

Preserves OHLC channel geometry as independent interpolated paths. Output is not a reconstructed candle series.

## zscore_close

Formula: `(close_t - mean(close_window)) / std(close_window)`.

Removes translation and amplitude. Uses only the observed pattern window, not future bars.

## range_close

Formula: `(close_t - min(close_window)) / (max(close_window) - min(close_window))`.

Optional centered form maps to `[-1, 1]`. Removes amplitude information and rejects zero range by default.

## volatility_targeted_return

Formula: cumulative log returns scaled by in-window log-return standard deviation.

Targets volatility invariance. Rejects near-zero volatility by default.

## atr_anchored_ohlc

Formula: `(OHLC_t - close_0) / ATR_window`.

ATR uses window-internal true range. The first true range is `high_0 - low_0`; no preceding bar outside the immutable window is used.

## volume_relative_mean

Formula: `volume_t / mean(volume_window)`.

Optional volume-only representation. Price normalization does not require volume.

