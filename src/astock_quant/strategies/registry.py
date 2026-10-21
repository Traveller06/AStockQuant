"""Explicit opt-in registry for strategy plug-ins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .weekly_trend.strategy import WeeklyTrendConfirmationStrategy


@dataclass(frozen=True)
class _LegacyV7Strategy:
    strategy_id: str = "legacy_v7"
    strategy_version: str = "7.6.3"


class StrategyRegistry:
    def __init__(self, *, default_strategy_id: str) -> None:
        self.default_strategy_id = default_strategy_id
        self._strategies: dict[str, Any] = {}

    @classmethod
    def with_builtins(cls) -> StrategyRegistry:
        registry = cls(default_strategy_id="legacy_v7")
        registry.register(_LegacyV7Strategy())
        registry.register(WeeklyTrendConfirmationStrategy())
        return registry

    def register(self, strategy: Any) -> None:
        strategy_id = getattr(strategy, "strategy_id", "")
        if not isinstance(strategy_id, str) or not strategy_id.strip():
            raise ValueError("strategy_id must not be empty")
        if strategy_id in self._strategies:
            raise ValueError(f"strategy {strategy_id!r} is already registered")
        self._strategies[strategy_id] = strategy

    def get(self, strategy_id: str) -> Any:
        try:
            return self._strategies[strategy_id]
        except KeyError as error:
            raise KeyError(f"unknown strategy: {strategy_id}") from error
