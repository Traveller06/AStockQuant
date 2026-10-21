from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from astock_quant.indicators.swing_detector import SwingKind, SwingPoint
from astock_quant.strategies.weekly_trend.risk import initial_stop, trend_exit


SHANGHAI = ZoneInfo("Asia/Shanghai")
SIGNAL_TIME = datetime(2026, 9, 25, 15, 0, tzinfo=SHANGHAI)


def test_initial_stop_uses_latest_low_confirmed_by_signal_time() -> None:
    swings = (
        SwingPoint(SwingKind.LOW, SIGNAL_TIME - timedelta(days=8), SIGNAL_TIME - timedelta(days=6), 9.10),
        SwingPoint(SwingKind.LOW, SIGNAL_TIME - timedelta(days=4), SIGNAL_TIME - timedelta(days=2), 9.42),
        SwingPoint(SwingKind.HIGH, SIGNAL_TIME - timedelta(days=3), SIGNAL_TIME - timedelta(days=1), 10.8),
        SwingPoint(SwingKind.LOW, SIGNAL_TIME - timedelta(days=1), SIGNAL_TIME + timedelta(days=1), 9.80),
    )

    assert initial_stop(swings, SIGNAL_TIME) == 9.42


def test_initial_stop_returns_none_without_visible_confirmed_low() -> None:
    future = SwingPoint(SwingKind.LOW, SIGNAL_TIME, SIGNAL_TIME + timedelta(days=2), 9.8)
    assert initial_stop((future,), SIGNAL_TIME) is None


@pytest.mark.parametrize(
    ("cause", "arguments"),
    (
        ("close_below_ma20", dict(weekly_close=9.9, ma20=10.0, ma_order_intact=True, swing_structure_intact=True)),
        ("ma_order_broken", dict(weekly_close=10.1, ma20=10.0, ma_order_intact=False, swing_structure_intact=True)),
        ("swing_structure_broken", dict(weekly_close=10.1, ma20=10.0, ma_order_intact=True, swing_structure_intact=False)),
    ),
)
def test_each_weekly_break_triggers_exit(cause: str, arguments: dict[str, object]) -> None:
    decision = trend_exit(as_of=SIGNAL_TIME, **arguments)

    assert decision.should_exit is True
    assert decision.reason_code == f"exit.{cause}"
    assert decision.reason_zh


def test_intact_weekly_trend_holds_position_and_ma20_boundary_is_inclusive() -> None:
    decision = trend_exit(
        weekly_close=10.0,
        ma20=10.0,
        ma_order_intact=True,
        swing_structure_intact=True,
        as_of=SIGNAL_TIME,
    )

    assert decision.should_exit is False
    assert decision.reason_code == "exit.hold"
    assert all(check.passed for check in decision.checks)
