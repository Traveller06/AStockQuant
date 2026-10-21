"""Versioned, immutable configuration for the weekly trend strategy."""

from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal

from astock_quant.core.models import JSONValue


@dataclass(frozen=True)
class WeeklyTrendConfig:
    strategy_id: str = "weekly_trend_confirmation"
    strategy_version: str = "1.0.0"
    parameter_version: str = "weekly-trend-v1"
    weekly_ma_periods: tuple[int, int, int] = (5, 10, 20)
    daily_ma_period: int = 10
    volume_lookback: int = 5
    breakout_volume_multiple: Decimal = Decimal("1.5")
    breakout_followthrough_volume_multiple: Decimal = Decimal("1.2")
    support_tolerance: Decimal = Decimal("0.03")
    setup_valid_sessions: int = 20
    stabilization_lookback: int = 3
    stabilization_low_tolerance: Decimal = Decimal("0.01")
    daily_volume_multiple: Decimal = Decimal("1.3")
    swing_left: int = 2
    swing_right: int = 2

    def __post_init__(self) -> None:
        for name in ("strategy_id", "strategy_version", "parameter_version"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")

        if (
            len(self.weekly_ma_periods) != 3
            or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in self.weekly_ma_periods)
            or tuple(sorted(self.weekly_ma_periods)) != self.weekly_ma_periods
            or len(set(self.weekly_ma_periods)) != 3
        ):
            raise ValueError("weekly_ma_periods must contain three positive strictly increasing periods")

        for name in (
            "daily_ma_period",
            "volume_lookback",
            "setup_valid_sessions",
            "stabilization_lookback",
            "swing_left",
            "swing_right",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

        for name in (
            "breakout_volume_multiple",
            "breakout_followthrough_volume_multiple",
            "daily_volume_multiple",
        ):
            value = getattr(self, name)
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{name} must be positive and finite")

        for name in ("support_tolerance", "stabilization_low_tolerance"):
            value = getattr(self, name)
            if not value.is_finite() or value < 0 or value >= 1:
                raise ValueError(f"{name} tolerance must be finite and in [0, 1)")

    def to_manifest_parameters(self) -> dict[str, JSONValue]:
        """Return a deterministic JSON-safe parameter snapshot."""

        result: dict[str, JSONValue] = {}
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, Decimal):
                result[field.name] = str(value)
            elif isinstance(value, tuple):
                result[field.name] = list(value)
            else:
                result[field.name] = value
        return result
