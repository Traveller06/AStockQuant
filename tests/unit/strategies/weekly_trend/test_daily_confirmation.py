from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from astock_quant.core.models import Bar
from astock_quant.strategies.weekly_trend.config import WeeklyTrendConfig
from astock_quant.strategies.weekly_trend.daily_confirmation import confirm_daily_setup
from astock_quant.strategies.weekly_trend.models import (
    PatternState,
    PatternStatus,
    SetupHit,
    SetupKind,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _state(kind: SetupKind, reference_price: float = 10.0) -> PatternState:
    created = datetime(2026, 9, 4, 15, 0, tzinfo=SHANGHAI)
    setup = SetupHit(kind, created, reference_price, "测试参考位", ())
    return PatternState(
        code="600000",
        status=PatternStatus.WAITING_CONFIRMATION,
        setup=setup,
        created_at=created,
        expires_on=date(2026, 10, 9),
        emitted_signal_id=None,
        strategy_version="1.0.0",
        parameter_version="weekly-trend-v1",
        data_cutoff=created,
    )


def _bars(
    *,
    current_low: float = 9.9,
    prior_three_low: float = 10.0,
    current_volume: float = 130.0,
    current_close: float = 10.2,
    current_open: float = 10.0,
    prior_closes: tuple[float, ...] | None = None,
    current_high: float = 10.3,
) -> tuple[Bar, ...]:
    closes = prior_closes or (10.0,) * 9
    start = datetime(2026, 9, 7, 15, 0, tzinfo=SHANGHAI)
    result: list[Bar] = []
    for index, close in enumerate(closes):
        low = prior_three_low if index >= len(closes) - 3 else min(prior_three_low, close - 0.1)
        high = max(close + 0.1, low + 0.2)
        result.append(
            Bar(
                code="600000",
                timestamp=start + timedelta(days=index),
                open=close,
                high=high,
                low=min(low, close),
                close=close,
                volume=100.0,
                amount=1000.0,
                source="fixture",
            )
        )
    timestamp = start + timedelta(days=len(closes))
    result.append(
        Bar(
            code="600000",
            timestamp=timestamp,
            open=current_open,
            high=max(current_high, current_open, current_close),
            low=min(current_low, current_open, current_close),
            close=current_close,
            volume=current_volume,
            amount=current_volume * current_close,
            source="fixture",
        )
    )
    return tuple(result)


def test_three_day_stabilization_uses_inclusive_one_percent_floor() -> None:
    bars = _bars(current_low=9.90, prior_three_low=10.00)

    result = confirm_daily_setup(_state(SetupKind.BREAKOUT), bars, WeeklyTrendConfig())

    assert result.confirmed is True
    assert next(check for check in result.checks if check.code == "confirm.stabilization.low").passed


def test_daily_volume_uses_prior_five_days_and_inclusive_1_3_multiple() -> None:
    result = confirm_daily_setup(
        _state(SetupKind.BREAKOUT),
        _bars(current_volume=130.0),
        WeeklyTrendConfig(),
    )

    assert result.confirmed is True
    volume = next(check for check in result.checks if check.code == "confirm.volume")
    assert volume.actual == "130"
    assert volume.passed is True


def test_breakout_confirmation_does_not_require_ma10() -> None:
    prior = (11.0,) * 8 + (10.0,)
    bars = _bars(prior_closes=prior, current_close=10.2, current_low=9.9, current_high=10.3)

    result = confirm_daily_setup(_state(SetupKind.BREAKOUT), bars, WeeklyTrendConfig())

    assert result.confirmed is True
    assert all(check.code != "confirm.ma10_reclaim" for check in result.checks)


@pytest.mark.parametrize("kind", (SetupKind.GOLDEN_CROSS, SetupKind.PULLBACK))
def test_golden_and_pullback_require_strict_close_above_ma10(kind: SetupKind) -> None:
    prior = (10.4,) * 8 + (8.6,)
    bars = _bars(prior_closes=prior, current_close=10.2, current_open=10.0)

    result = confirm_daily_setup(_state(kind), bars, WeeklyTrendConfig())

    assert result.confirmed is False
    ma10 = next(check for check in result.checks if check.code == "confirm.ma10_reclaim")
    assert ma10.actual == "10.2"
    assert ma10.passed is False


def test_confirmation_rejects_expired_or_non_waiting_state() -> None:
    bars = _bars()
    expired = _state(SetupKind.BREAKOUT)
    expired = PatternState(**{**expired.__dict__, "expires_on": date(2026, 9, 15)})

    assert confirm_daily_setup(expired, bars, WeeklyTrendConfig()).confirmed is False
    with pytest.raises(ValueError, match="waiting"):
        confirm_daily_setup(
            PatternState(**{**_state(SetupKind.BREAKOUT).__dict__, "status": PatternStatus.EXPIRED}),
            bars,
            WeeklyTrendConfig(),
        )
