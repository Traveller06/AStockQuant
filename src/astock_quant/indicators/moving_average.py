"""Causal moving-average calculations with explicit unavailable values."""

from __future__ import annotations

from collections.abc import Sequence
from math import isfinite
from numbers import Real


def _validated(values: Sequence[float], period: int) -> tuple[float, ...]:
    if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
        raise ValueError("period must be a positive integer")

    normalized: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("values must be finite numbers")
        number = float(value)
        if not isfinite(number):
            raise ValueError("values must be finite numbers")
        normalized.append(number)
    return tuple(normalized)


def moving_average(values: Sequence[float], period: int) -> tuple[float | None, ...]:
    """Return a same-length trailing mean that includes the current value."""

    numbers = _validated(values, period)
    result: list[float | None] = []
    window_sum = 0.0
    for index, value in enumerate(numbers):
        window_sum += value
        if index >= period:
            window_sum -= numbers[index - period]
        result.append(window_sum / period if index >= period - 1 else None)
    return tuple(result)


def rolling_mean_before(values: Sequence[float], period: int) -> tuple[float | None, ...]:
    """Return the trailing mean of the *prior* ``period`` values at each index."""

    numbers = _validated(values, period)
    result: list[float | None] = []
    window_sum = 0.0
    for index, value in enumerate(numbers):
        result.append(window_sum / period if index >= period else None)
        window_sum += value
        if index >= period:
            window_sum -= numbers[index - period]
    return tuple(result)
