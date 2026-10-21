from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from astock_quant.core.models import Bar
from astock_quant.data.calendar import TradingCalendar
from astock_quant.strategies.weekly_trend.models import PatternState, PatternStatus, SetupHit, SetupKind
from astock_quant.strategies.weekly_trend.strategy import WeeklyTrendConfirmationStrategy


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _fixture():
    first = date(2026, 1, 9)
    sessions = tuple(first + timedelta(days=7 * index) for index in range(45))
    bars = []
    for index, session in enumerate(sessions[:25]):
        close = 10.0 + index * 0.4
        high = close + (2.0 if index in (5, 12) else 0.2)
        low = close - (2.0 if index in (7, 14) else 0.2)
        volume = 150.0 if index == 24 else 100.0
        bars.append(
            Bar(
                code="600000",
                timestamp=datetime.combine(session, time(15, 0), SHANGHAI),
                open=close - 0.1,
                high=high,
                low=low,
                close=close,
                volume=volume,
                amount=volume * close,
                source="fixture",
            )
        )
    created = bars[20].timestamp
    setup = SetupHit(SetupKind.BREAKOUT, created, 19.5, "既有突破位", ())
    state = PatternState(
        code="600000",
        status=PatternStatus.WAITING_CONFIRMATION,
        setup=setup,
        created_at=created,
        expires_on=sessions[39],
        emitted_signal_id=None,
        strategy_version="1.0.0",
        parameter_version="weekly-trend-v1",
        data_cutoff=created,
    )
    return {
        "source_run_id": "run-1",
        "daily_bars": tuple(bars),
        "adjustment_basis": "forward",
        "calendar": TradingCalendar(sessions),
        "as_of": bars[-1].timestamp + timedelta(minutes=1),
        "state": state,
    }


def test_evaluate_returns_one_signal_stop_and_complete_chinese_decision() -> None:
    arguments = _fixture()

    result = WeeklyTrendConfirmationStrategy().evaluate(**arguments)

    assert result.signal is not None
    assert result.signal.strategy_id == "weekly_trend_confirmation"
    assert result.signal.timestamp == arguments["daily_bars"][-1].timestamp
    assert result.initial_stop == pytest.approx(13.6)
    assert result.next_state.status is PatternStatus.CONFIRMED
    assert result.next_state.emitted_signal_id == result.signal.signal_id
    assert result.decision.reason_zh
    assert all(check.reason_zh for check in result.decision.all_checks)


def test_appending_future_data_does_not_change_evaluation_at_original_cutoff() -> None:
    arguments = _fixture()
    prefix = WeeklyTrendConfirmationStrategy().evaluate(**arguments)
    last = arguments["daily_bars"][-1]
    future_timestamp = last.timestamp + timedelta(days=7)
    future = Bar(
        code=last.code,
        timestamp=future_timestamp,
        open=1.0,
        high=1.1,
        low=0.9,
        close=1.0,
        volume=1000.0,
        amount=1000.0,
        source="fixture",
    )

    extended = WeeklyTrendConfirmationStrategy().evaluate(
        **{**arguments, "daily_bars": arguments["daily_bars"] + (future,)}
    )

    assert extended == prefix
