import pytest

from astock_quant.strategies.registry import StrategyRegistry


def test_weekly_confirmation_is_available_but_not_default() -> None:
    registry = StrategyRegistry.with_builtins()

    assert registry.get("weekly_trend_confirmation").strategy_id == "weekly_trend_confirmation"
    assert registry.default_strategy_id != "weekly_trend_confirmation"


def test_registry_rejects_duplicate_and_unknown_ids() -> None:
    registry = StrategyRegistry.with_builtins()
    weekly = registry.get("weekly_trend_confirmation")

    with pytest.raises(ValueError, match="already registered"):
        registry.register(weekly)
    with pytest.raises(KeyError, match="unknown strategy"):
        registry.get("missing")
