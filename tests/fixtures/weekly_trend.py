from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from astock_quant.indicators.swing_detector import SwingKind, SwingPoint
from astock_quant.indicators.weekly_bars import WeeklyBar


SHANGHAI = ZoneInfo("Asia/Shanghai")


def rising_weeks(count: int = 22) -> tuple[WeeklyBar, ...]:
    first_end = datetime(2026, 1, 9, 15, 0, tzinfo=SHANGHAI)
    weeks: list[WeeklyBar] = []
    for index in range(count):
        close = 10.0 + index * 0.5
        end = first_end + timedelta(days=index * 7)
        weeks.append(
            WeeklyBar(
                code="600000",
                start=end - timedelta(days=4),
                end=end,
                open=close - 0.2,
                high=close + 0.4,
                low=close - 0.5,
                close=close,
                volume=1000.0 + index * 20,
                amount=(1000.0 + index * 20) * close,
                source="fixture",
            )
        )
    return tuple(weeks)


def rising_swings(weeks: tuple[WeeklyBar, ...]) -> tuple[SwingPoint, ...]:
    return (
        SwingPoint(SwingKind.HIGH, weeks[5].end, weeks[7].end, 13.0),
        SwingPoint(SwingKind.LOW, weeks[7].end, weeks[9].end, 12.0),
        SwingPoint(SwingKind.HIGH, weeks[12].end, weeks[14].end, 16.5),
        SwingPoint(SwingKind.LOW, weeks[14].end, weeks[16].end, 15.0),
    )
