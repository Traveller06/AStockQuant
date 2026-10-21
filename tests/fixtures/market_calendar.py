from datetime import date, datetime
from zoneinfo import ZoneInfo

from astock_quant.core.models import Bar


SHANGHAI = ZoneInfo("Asia/Shanghai")


def at_close(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 15, 0, tzinfo=SHANGHAI)


def fixture_sessions() -> tuple[date, ...]:
    return (
        date(2026, 9, 30),
        date(2026, 10, 1),
        date(2026, 10, 2),
        date(2026, 10, 5),
        date(2026, 10, 6),
        date(2026, 10, 7),
        date(2026, 10, 8),
        date(2026, 10, 9),
    )


def fixture_bars() -> tuple[Bar, ...]:
    values = (
        (2026, 9, 30, 10.0, 10.8, 9.8, 10.5, 100.0, 1020.0),
        (2026, 10, 1, 10.5, 11.2, 10.2, 11.0, 120.0, 1300.0),
        (2026, 10, 2, 11.0, 11.5, 10.7, 11.3, 140.0, 1550.0),
        (2026, 10, 5, 11.3, 11.6, 11.0, 11.4, 130.0, 1480.0),
        (2026, 10, 6, 11.4, 11.8, 11.2, 11.7, 150.0, 1740.0),
        (2026, 10, 7, 11.7, 11.9, 11.4, 11.5, 160.0, 1840.0),
    )
    return tuple(
        Bar(
            code="600000",
            timestamp=at_close(year, month, day),
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
            amount=amount,
            source="fixture",
        )
        for year, month, day, open_price, high, low, close, volume, amount in values
    )
