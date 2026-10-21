from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from astock_quant.backtest.matcher import match_next_session
from astock_quant.backtest.models import ExecutionBar, LedgerPosition, MatchStatus
from astock_quant.core.enums import Side
from astock_quant.core.models import Bar, Signal


SHANGHAI = ZoneInfo("Asia/Shanghai")


def at(day: int, hour: int = 15) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=SHANGHAI)


def signal(side: Side, day: int) -> Signal:
    return Signal.new(
        source_run_id="run-1",
        strategy_id="weekly_trend_confirmation",
        code="600000",
        timestamp=at(day),
        side=side,
        strength=1.0,
        reason="测试信号",
        parameter_version="weekly-trend-v1",
    )


def execution(day: int, **flags: bool) -> ExecutionBar:
    return ExecutionBar(
        bar=Bar(
            code="600000",
            timestamp=at(day, 9),
            open=10.0,
            high=10.5,
            low=9.8,
            close=10.2,
            volume=1_000_000,
            amount=10_100_000,
            source="fixture",
        ),
        **flags,
    )


def position(opened_day: int) -> LedgerPosition:
    return LedgerPosition(
        code="600000",
        shares=100,
        average_cost="10.00",
        opened_at=at(opened_day, 9),
    )


def test_close_signal_cannot_fill_on_same_session() -> None:
    result = match_next_session(signal(Side.BUY, 10), execution(10), position=None)

    assert result.status is MatchStatus.PENDING_ENTRY
    assert result.reason_code == "match.next_session"
    assert result.trade is None


def test_close_signal_fills_only_on_next_session() -> None:
    buy = signal(Side.BUY, 10)

    result = match_next_session(buy, execution(11), position=None)

    assert result.status is MatchStatus.FILLED
    assert result.trade is not None
    assert result.trade.traded_at > buy.timestamp
    assert result.trade.price == pytest.approx(10.0)


def test_same_day_sell_waits_for_t_plus_one() -> None:
    result = match_next_session(signal(Side.SELL, 11), execution(11), position(11))

    assert result.status is MatchStatus.PENDING_EXIT
    assert result.reason_code == "match.t_plus_one"


@pytest.mark.parametrize(
    ("flags", "reason"),
    [
        ({"is_suspended": True}, "match.suspended_entry"),
        ({"at_limit_up": True}, "match.limit_up_entry"),
    ],
)
def test_unavailable_entry_is_cancelled_once(flags: dict[str, bool], reason: str) -> None:
    result = match_next_session(signal(Side.BUY, 10), execution(11, **flags), position=None)

    assert result.status is MatchStatus.CANCELLED_ENTRY
    assert result.reason_code == reason
    assert result.trade is None


@pytest.mark.parametrize(
    ("flags", "reason"),
    [
        ({"is_suspended": True}, "match.suspended_exit"),
        ({"at_limit_down": True}, "match.limit_down_exit"),
    ],
)
def test_unavailable_exit_remains_pending(flags: dict[str, bool], reason: str) -> None:
    result = match_next_session(signal(Side.SELL, 11), execution(12, **flags), position(10))

    assert result.status is MatchStatus.PENDING_EXIT
    assert result.reason_code == reason
    assert result.trade is None


def test_sell_without_a_position_is_rejected() -> None:
    result = match_next_session(signal(Side.SELL, 10), execution(11), position=None)

    assert result.status is MatchStatus.REJECTED
    assert result.reason_code == "match.no_position"


def test_execution_flags_cannot_contradict_each_other() -> None:
    with pytest.raises(ValueError, match="limit"):
        replace(execution(11), at_limit_up=True, at_limit_down=True)
