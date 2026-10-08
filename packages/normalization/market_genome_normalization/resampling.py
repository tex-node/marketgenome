from __future__ import annotations

import math

import numpy as np


def resample_channel(values: list[float], points: int, method: str = "linear") -> list[float]:
    if points < 2:
        raise ValueError("NORMALIZATION_CONFIGURATION_INVALID")
    array = np.asarray(values, dtype=np.float64)
    if array.size < 2:
        raise ValueError("NORMALIZATION_INTERPOLATION_FAILED")
    if not np.all(np.isfinite(array)):
        raise ValueError("NORMALIZATION_NON_FINITE_INPUT")
    if array.size == points:
        return [float(x) for x in array]
    source_x = np.linspace(0.0, 1.0, array.size)
    target_x = np.linspace(0.0, 1.0, points)
    if method == "linear":
        result = np.interp(target_x, source_x, array)
    elif method == "previous":
        indexes = np.searchsorted(source_x, target_x, side="right") - 1
        indexes = np.clip(indexes, 0, array.size - 1)
        result = array[indexes]
        result[-1] = array[-1]
    else:
        raise ValueError("NORMALIZATION_CONFIGURATION_INVALID")
    if not np.all(np.isfinite(result)):
        raise ValueError("NORMALIZATION_NON_FINITE_OUTPUT")
    result[0] = array[0]
    result[-1] = array[-1]
    return [float(0.0 if math.isclose(float(x), 0.0, abs_tol=1e-15) else x) for x in result]


def resample_channels(values: dict[str, list[float]], points: int, method: str = "linear") -> dict[str, list[float]]:
    return {channel: resample_channel(series, points, method) for channel, series in values.items()}

