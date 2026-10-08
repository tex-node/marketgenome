from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizationMethodDefinition:
    code: str
    label: str
    version: str
    description: str
    is_price_scale_invariant: bool
    is_translation_invariant: bool
    is_amplitude_invariant: bool
    is_volatility_adjusted: bool
    supports_ohlc: bool
    supports_volume: bool
    minimum_bars: int
    channels: list[str]
    channel_schema: str


METHODS: dict[str, NormalizationMethodDefinition] = {
    "anchored_simple_return": NormalizationMethodDefinition(
        "anchored_simple_return", "Anchored simple return", "normalization_v1",
        "close_t / close_0 - 1", True, False, False, False, False, False, 2, ["close"], "close_path_v1",
    ),
    "anchored_log_return": NormalizationMethodDefinition(
        "anchored_log_return", "Anchored log return", "normalization_v1",
        "log(close_t / close_0)", True, False, False, False, False, False, 2, ["close"], "close_path_v1",
    ),
    "zscore_close": NormalizationMethodDefinition(
        "zscore_close", "Window close z-score", "normalization_v1",
        "(close_t - mean(close_window)) / std(close_window)", True, True, True, False, False, False, 2, ["close"], "close_path_v1",
    ),
    "range_close": NormalizationMethodDefinition(
        "range_close", "Window close range", "normalization_v1",
        "(close_t - min(close_window)) / (max(close_window) - min(close_window))", True, True, True, False, False, False, 2, ["close"], "close_path_v1",
    ),
    "volatility_targeted_return": NormalizationMethodDefinition(
        "volatility_targeted_return", "Volatility-targeted return path", "normalization_v1",
        "cumulative log returns scaled by in-window return volatility", True, False, True, True, False, False, 3, ["close"], "close_path_v1",
    ),
    "anchored_ohlc": NormalizationMethodDefinition(
        "anchored_ohlc", "Anchored OHLC simple return", "normalization_v1",
        "OHLC / close_0 - 1", True, False, False, False, True, False, 2, ["open", "high", "low", "close"], "ohlc_path_v1",
    ),
    "atr_anchored_ohlc": NormalizationMethodDefinition(
        "atr_anchored_ohlc", "ATR-anchored OHLC", "normalization_v1",
        "(OHLC - close_0) / window_internal_ATR", True, True, False, True, True, False, 2, ["open", "high", "low", "close"], "ohlc_path_v1",
    ),
    "volume_relative_mean": NormalizationMethodDefinition(
        "volume_relative_mean", "Relative mean volume", "normalization_v1",
        "volume_t / mean(volume_window)", False, False, True, False, False, True, 2, ["volume"], "volume_path_v1",
    ),
}


def list_methods() -> list[NormalizationMethodDefinition]:
    return list(METHODS.values())


def get_method(code: str) -> NormalizationMethodDefinition:
    try:
        return METHODS[code]
    except KeyError as exc:
        raise ValueError("NORMALIZATION_METHOD_NOT_FOUND") from exc

