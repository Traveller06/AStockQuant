from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from astock_quant.core.models import Bar
from astock_quant.indicators.swing_detector import SwingKind, confirmed_swings
from astock_quant.indicators.weekly_bars import WeeklyBar


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _bars(highs: tuple[float, ...], lows: tuple[float, ...]) -> tuple[Bar, ...]:
    start = datetime(2026, 1, 5, 15, 0, tzinfo=SHANGHAI)
    return tuple(
        Bar(
            code="600000",
            timestamp=start + timedelta(days=index),
            open=(high + low) / 2,
            high=high,
            low=low,
            close=(high + low) / 2,
            volume=100.0,
            amount=1000.0,
            source="fixture",
        )
        for index, (high, low) in enumerate(zip(highs, lows, strict=True))
    )


@pytest.fixture
def swing_bars() -> tuple[Bar, ...]:
    return _bars(
        highs=(10.0, 12.0, 18.0, 14.0, 13.0, 15.0, 16.0),
        lows=(8.0, 9.0, 11.0, 10.0, 7.0, 9.0, 10.0),
    )


def test_swing_becomes_visible_only_on_confirmation_bar(swing_bars: tuple[Bar, ...]) -> None:
    points = confirmed_swings(swing_bars, left=2, right=2)
    high = next(point for point in points if point.kind is SwingKind.HIGH)

    assert high.pivot_at == swing_bars[2].timestamp
    assert high.confirmed_at == swing_bars[4].timestamp
    assert high.price == 18.0

    before_confirmation = confirmed_swings(swing_bars[:4], left=2, right=2)
    assert all(point.pivot_at != swing_bars[2].timestamp for point in before_confirmation)


def test_appending_future_bars_does_not_change_existing_confirmed_points(
    swing_bars: tuple[Bar, ...],
) -> None:
    future_bars = _bars(
        highs=(17.0, 25.0, 18.0),
        lows=(11.0, 12.0, 10.0),
    )
    offset = swing_bars[-1].timestamp + timedelta(days=1) - future_bars[0].timestamp
    future_bars = tuple(
        Bar(**{**bar.__dict__, "timestamp": bar.timestamp + offset}) for bar in future_bars
    )

    prefix = confirmed_swings(swing_bars, left=2, right=2)
    extended = tuple(
        point
        for point in confirmed_swings(swing_bars + future_bars, left=2, right=2)
        if point.confirmed_at <= swing_bars[-1].timestamp
    )

    assert extended == prefix


def test_equal_neighboring_extrema_do_not_create_swings() -> None:
    bars = _bars(
        highs=(10.0, 12.0, 18.0, 18.0, 13.0),
        lows=(8.0, 9.0, 11.0, 10.0, 9.0),
    )

    assert all(point.kind is not SwingKind.HIGH for point in confirmed_swings(bars, 2, 2))


def test_invalid_widths_and_non_increasing_timestamps_are_rejected(
    swing_bars: tuple[Bar, ...],
) -> None:
    with pytest.raises(ValueError, match="left"):
        confirmed_swings(swing_bars, left=0, right=2)
    with pytest.raises(ValueError, match="right"):
        confirmed_swings(swing_bars, left=2, right=-1)
    with pytest.raises(ValueError, match="strictly increasing"):
        confirmed_swings(tuple(reversed(swing_bars)), left=2, right=2)


def test_weekly_bars_use_end_as_pivot_and_confirmation_time() -> None:
    daily = _bars(
        highs=(10.0, 12.0, 18.0, 14.0, 13.0),
        lows=(8.0, 9.0, 11.0, 10.0, 9.0),
    )
    weekly = tuple(
        WeeklyBar(
            code=bar.code,
            start=bar.timestamp - timedelta(days=4),
            end=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            amount=bar.amount,
            source=bar.source,
        )
        for bar in daily
    )

    point = next(point for point in confirmed_swings(weekly, 2, 2) if point.kind is SwingKind.HIGH)
    assert point.pivot_at == weekly[2].end
    assert point.confirmed_at == weekly[4].end
