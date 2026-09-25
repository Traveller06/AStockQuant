"""Causal swing-point detection with explicit confirmation timestamps."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from astock_quant.core.models import Bar
from astock_quant.indicators.weekly_bars import WeeklyBar


class SwingKind(str, Enum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True)
class SwingPoint:
    kind: SwingKind
    pivot_at: datetime
    confirmed_at: datetime
    price: float


def _timestamp(bar: Bar | WeeklyBar) -> datetime:
    return bar.timestamp if isinstance(bar, Bar) else bar.end


def _validate(bars: Sequence[Bar | WeeklyBar], left: int, right: int) -> tuple[datetime, ...]:
    if isinstance(left, bool) or not isinstance(left, int) or left <= 0:
        raise ValueError("left must be a positive integer")
    if isinstance(right, bool) or not isinstance(right, int) or right <= 0:
        raise ValueError("right must be a positive integer")

    timestamps = tuple(_timestamp(bar) for bar in bars)
    if any(timestamp.tzinfo is None or timestamp.utcoffset() is None for timestamp in timestamps):
        raise ValueError("bar timestamps must be timezone-aware")
    if any(previous >= current for previous, current in zip(timestamps, timestamps[1:])):
        raise ValueError("bar timestamps must be strictly increasing")
    if len({bar.code for bar in bars}) > 1:
        raise ValueError("bars must contain exactly one code")
    if any(not isfinite(bar.high) or not isfinite(bar.low) for bar in bars):
        raise ValueError("bar prices must be finite")
    return timestamps


def confirmed_swings(
    bars: Sequence[Bar | WeeklyBar],
    left: int,
    right: int,
) -> tuple[SwingPoint, ...]:
    """Return strict extrema only after their full right window is observable."""

    timestamps = _validate(bars, left, right)
    points: list[SwingPoint] = []
    for pivot_index in range(left, len(bars) - right):
        pivot = bars[pivot_index]
        neighbors = bars[pivot_index - left : pivot_index] + bars[
            pivot_index + 1 : pivot_index + right + 1
        ]
        confirmed_at = timestamps[pivot_index + right]
        if all(pivot.high > neighbor.high for neighbor in neighbors):
            points.append(
                SwingPoint(SwingKind.HIGH, timestamps[pivot_index], confirmed_at, pivot.high)
            )
        if all(pivot.low < neighbor.low for neighbor in neighbors):
            points.append(
                SwingPoint(SwingKind.LOW, timestamps[pivot_index], confirmed_at, pivot.low)
            )
    return tuple(points)
