"""Public protocol implemented by strategy plug-ins."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from astock_quant.core.models import Bar
from astock_quant.data.calendar import TradingCalendar
from astock_quant.strategies.weekly_trend.models import PatternState, StrategyEvaluation


class Strategy(Protocol):
    strategy_id: str
    strategy_version: str

    def evaluate(
        self,
        *,
        source_run_id: str,
        daily_bars: Sequence[Bar],
        adjustment_basis: str,
        calendar: TradingCalendar,
        as_of: datetime,
        state: PatternState,
    ) -> StrategyEvaluation: ...
