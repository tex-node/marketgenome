# Resampling engine

Resampling maps each normalized source channel from source positions `0.0 ... 1.0` onto a fixed target grid with `M` equally spaced points.

Supported methods:

- `linear`: NumPy linear interpolation. First and last endpoints are forced to match the source endpoints.
- `previous`: stepwise previous-value interpolation. The last output point is forced to the source endpoint.

OHLC uses independent path channels in this phase. The output is an interpolated channel representation, not synthetic tradable candles.

