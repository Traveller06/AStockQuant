from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from astock_quant.backtest.engine import BacktestRequest
from astock_quant.backtest.fees import FeeSchedule
from astock_quant.backtest.models import ExecutionBar
from astock_quant.core.enums import Side
from astock_quant.core.models import Bar, Signal
from astock_quant.data.calendar import TradingCalendar
from astock_quant.reports.run_store import RunStore
from astock_quant.services.weekly_trend_service import WeeklyTrendService
from astock_quant.strategies.weekly_trend.config import WeeklyTrendConfig


SHANGHAI = ZoneInfo("Asia/Shanghai")
SESSIONS = (date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17))


@dataclass(frozen=True)
class ScriptedDecision:
    code: str
    evaluated_at: datetime
    reason_code: str
    reason_zh: str
    all_checks: tuple = ()


@dataclass(frozen=True)
class ScriptedEvaluation:
    signal: Signal | None
    decision: ScriptedDecision
    next_state: object
    initial_stop: float | None


class ScriptedStrategy:
    strategy_id = "weekly_trend_confirmation"
    strategy_version = "1.0.0"
    minimum_bars = 1
    config = WeeklyTrendConfig()

    def evaluate(self, *, source_run_id, daily_bars, adjustment_basis, calendar, as_of, state):
        if daily_bars[0].code == "600001":
            raise ValueError("脚本化单股数据错误")
        first_day = daily_bars[0].timestamp.date()
        entry = None
        stop = None
        if as_of.date() == first_day:
            entry = Signal.new(
                source_run_id=source_run_id,
                strategy_id=self.strategy_id,
                code=daily_bars[0].code,
                timestamp=as_of,
                side=Side.BUY,
                strength=1.0,
                reason="脚本化确认信号",
                parameter_version=self.config.parameter_version,
            )
            stop = 9.5
        return ScriptedEvaluation(
            signal=entry,
            decision=ScriptedDecision(daily_bars[0].code, as_of, "scripted", "脚本化测试决定"),
            next_state=state,
            initial_stop=stop,
        )


def make_request(*, flags: dict[date, dict[str, bool]] | None = None, days: int = 4) -> BacktestRequest:
    flags = flags or {}
    daily = []
    execution = []
    for index, session in enumerate(SESSIONS[:days]):
        low = 9.0 if index == 2 else (8.9 if index >= 3 else 9.8)
        close = 10.1 if index < 3 else 9.0
        daily.append(
            Bar(
                code="600000",
                timestamp=datetime.combine(session, time(15), SHANGHAI),
                open=10.0,
                high=10.5,
                low=low,
                close=close,
                volume=1_000_000,
                amount=10_000_000,
                source="fixture",
            )
        )
        execution.append(
            ExecutionBar(
                Bar(
                    code="600000",
                    timestamp=datetime.combine(session, time(9, 30), SHANGHAI),
                    open=10.0 if index < 3 else 9.0,
                    high=10.5,
                    low=8.9 if index >= 3 else 9.8,
                    close=close,
                    volume=1_000_000,
                    amount=10_000_000,
                    source="fixture",
                ),
                **flags.get(session, {}),
            )
        )
    return BacktestRequest(
        daily_bars={"600000": tuple(daily)},
        execution_bars={"600000": tuple(execution)},
        calendar=TradingCalendar(SESSIONS[:days]),
        initial_cash=Decimal("100000"),
        fees=FeeSchedule.default(),
        adjustment_basis="forward",
        data_as_of=SESSIONS[days - 1],
        app_version="8.0.0",
    )


def service(tmp_path, **kwargs) -> WeeklyTrendService:
    return WeeklyTrendService(RunStore(tmp_path / "runs"), strategy=ScriptedStrategy(), **kwargs)


def test_frozen_run_reconciles_signals_trades_cash_and_equity(tmp_path) -> None:
    result = service(tmp_path).run_backtest(make_request())

    assert len(result.signals) == 1
    assert [trade.side for trade in result.trades] == [Side.BUY, Side.SELL]
    assert result.snapshots[-1].cash >= 0
    assert result.reconciles_to_cent()


def test_limit_up_entry_is_cancelled_once_and_never_retried(tmp_path) -> None:
    request = make_request(flags={SESSIONS[1]: {"at_limit_up": True}})

    result = service(tmp_path).run_backtest(request)

    assert result.trades == ()
    assert [event.code for event in result.events].count("match.limit_up_entry") == 1


def test_limit_down_exit_remains_pending_until_tradable_session(tmp_path) -> None:
    request = make_request(
        flags={SESSIONS[3]: {"at_limit_down": True}, SESSIONS[4]: {"at_limit_down": True}},
        days=6,
    )

    result = service(tmp_path).run_backtest(request)

    assert result.trades[-1].traded_at.date() == SESSIONS[5]
    assert [event.code for event in result.events].count("match.limit_down_exit") == 2


def test_per_symbol_strategy_error_does_not_abort_other_symbols(tmp_path) -> None:
    request = make_request()
    bad = tuple(
        Bar(
            code="600001",
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            amount=bar.amount,
            source=bar.source,
        )
        for bar in request.daily_bars["600000"]
    )
    request = BacktestRequest(
        **{**request.__dict__, "daily_bars": {**request.daily_bars, "600001": bad}}
    )

    result = service(tmp_path).run_backtest(request)

    assert len(result.trades) == 2
    assert any(error["symbol"] == "600001" for error in result.errors)
