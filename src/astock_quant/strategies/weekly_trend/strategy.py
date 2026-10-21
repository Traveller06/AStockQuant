"""Pure coordinator for the weekly trend confirmation strategy."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from astock_quant.core.enums import Side
from astock_quant.core.models import Bar, Signal
from astock_quant.data.calendar import TradingCalendar
from astock_quant.indicators.swing_detector import confirmed_swings
from astock_quant.indicators.weekly_bars import aggregate_completed_weeks

from .config import WeeklyTrendConfig
from .daily_confirmation import confirm_daily_setup
from .models import (
    ConfirmationResult,
    DecisionAction,
    PatternState,
    PatternStatus,
    StrategyDecision,
    StrategyEvaluation,
)
from .risk import initial_stop
from .setups import detect_setups
from .state_machine import advance_state
from .trend import assess_weekly_trend


class WeeklyTrendConfirmationStrategy:
    strategy_id = "weekly_trend_confirmation"
    strategy_version = "1.0.0"

    def __init__(self, config: WeeklyTrendConfig | None = None) -> None:
        self.config = config or WeeklyTrendConfig()

    def evaluate(
        self,
        *,
        source_run_id: str,
        daily_bars: Sequence[Bar],
        adjustment_basis: str,
        calendar: TradingCalendar,
        as_of: datetime,
        state: PatternState,
    ) -> StrategyEvaluation:
        weeks = aggregate_completed_weeks(daily_bars, adjustment_basis, calendar, as_of)
        if not weeks:
            raise ValueError("weekly strategy requires at least one completed week")
        weekly_swings = confirmed_swings(weeks, self.config.swing_left, self.config.swing_right)
        trend = assess_weekly_trend(weeks, weekly_swings, self.config, as_of=as_of)
        setups = detect_setups(weeks, weekly_swings, trend, self.config, as_of=as_of)

        visible_daily = tuple(bar for bar in daily_bars if bar.timestamp <= as_of)
        if not visible_daily:
            raise ValueError("weekly strategy requires visible daily bars")
        if state.status is PatternStatus.WAITING_CONFIRMATION:
            confirmation = confirm_daily_setup(state, visible_daily, self.config, as_of=as_of)
        else:
            confirmation = ConfirmationResult(
                False,
                (),
                as_of,
                "confirm.not_waiting",
                "当前没有等待确认的形态",
            )

        signal: Signal | None = None
        stop: float | None = None
        if trend.qualified and confirmation.confirmed:
            signal = Signal.new(
                source_run_id=source_run_id,
                strategy_id=self.strategy_id,
                code=state.code,
                timestamp=visible_daily[-1].timestamp,
                side=Side.BUY,
                strength=1.0,
                reason=confirmation.reason_zh,
                parameter_version=self.config.parameter_version,
            )
            daily_swings = confirmed_swings(
                visible_daily,
                self.config.swing_left,
                self.config.swing_right,
            )
            stop = initial_stop(daily_swings, signal.timestamp)

        next_state = advance_state(
            state,
            visible_daily[-1].timestamp.date(),
            trend,
            confirmation,
            setups.selected,
            calendar_sessions=calendar.sessions,
            config=self.config,
            signal_id=signal.signal_id if signal else None,
        )
        if signal is not None:
            action = DecisionAction.EMIT_SIGNAL
            reason_code = "decision.confirmed"
            reason_zh = "日线确认通过，发出下一交易日买入意图"
        elif next_state.status is PatternStatus.INVALIDATED:
            action, reason_code, reason_zh = DecisionAction.INVALIDATE, "decision.invalidated", "周线趋势破坏，形态失效"
        elif next_state.status is PatternStatus.EXPIRED:
            action, reason_code, reason_zh = DecisionAction.EXPIRE, "decision.expired", "形态超过有效期"
        elif next_state.status is PatternStatus.WAITING_CONFIRMATION:
            action, reason_code, reason_zh = DecisionAction.WAIT, "decision.waiting", "形态有效，继续等待日线确认"
        else:
            action, reason_code, reason_zh = DecisionAction.IGNORE, "decision.ignored", "当前没有可执行信号"

        checks = trend.checks + setups.checks + confirmation.checks
        decision = StrategyDecision(
            code=state.code,
            evaluated_at=as_of,
            data_cutoff=visible_daily[-1].timestamp,
            strategy_version=self.strategy_version,
            parameter_version=self.config.parameter_version,
            trend=trend,
            setups=setups,
            confirmation=confirmation,
            previous_status=state.status,
            next_status=next_state.status,
            expires_on=next_state.expires_on,
            action=action,
            reason_code=reason_code,
            reason_zh=reason_zh,
            all_checks=checks,
        )
        return StrategyEvaluation(signal, decision, next_state, stop)
