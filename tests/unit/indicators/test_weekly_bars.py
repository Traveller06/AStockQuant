from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from astock_quant.core.errors import StrategyInputError
from astock_quant.data.calendar import TradingCalendar
from astock_quant.indicators.weekly_bars import aggregate_completed_weeks
from tests.fixtures.market_calendar import SHANGHAI, fixture_bars, fixture_sessions


AS_OF_WEDNESDAY = datetime(2026, 10, 7, 15, 1, tzinfo=SHANGHAI)


def test_rejects_unsorted_duplicate_mixed_code_and_mixed_basis() -> None:
    bars = fixture_bars()
    calendar = TradingCalendar(fixture_sessions())

    with pytest.raises(StrategyInputError, match="strictly increasing"):
        aggregate_completed_weeks(tuple(reversed(bars)), "forward", calendar, AS_OF_WEDNESDAY)
    with pytest.raises(StrategyInputError, match="duplicate"):
        aggregate_completed_weeks(bars + (bars[-1],), "forward", calendar, AS_OF_WEDNESDAY)
    with pytest.raises(StrategyInputError, match="one code"):
        aggregate_completed_weeks(
            bars[:-1] + (replace(bars[-1], code="000001"),),
            "forward",
            calendar,
            AS_OF_WEDNESDAY,
        )
    with pytest.raises(StrategyInputError, match="adjustment basis"):
        aggregate_completed_weeks(bars, "mixed", calendar, AS_OF_WEDNESDAY)


def test_calendar_requires_unique_increasing_sessions_and_aware_cutoff() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        TradingCalendar((date(2026, 10, 2), date(2026, 10, 1)))
    with pytest.raises(ValueError, match="duplicate"):
        TradingCalendar((date(2026, 10, 1), date(2026, 10, 1)))

    with pytest.raises(StrategyInputError, match="timezone-aware"):
        aggregate_completed_weeks(
            fixture_bars(),
            "forward",
            TradingCalendar(fixture_sessions()),
            datetime(2026, 10, 7, 15, 1),
        )


def test_holiday_shortened_week_is_complete_but_open_week_is_excluded() -> None:
    source = fixture_bars()
    before = tuple(source)

    weeks = aggregate_completed_weeks(
        source,
        "forward",
        TradingCalendar(fixture_sessions()),
        AS_OF_WEDNESDAY,
    )

    assert source == before
    assert len(weeks) == 1
    week = weeks[0]
    assert week.start.date().isoformat() == "2026-09-30"
    assert week.end.date().isoformat() == "2026-10-02"
    assert week.start.tzinfo is not None and week.end.tzinfo is not None
    assert (week.open, week.high, week.low, week.close) == (10.0, 11.5, 9.8, 11.3)
    assert week.volume == 360.0
    assert week.amount == 3870.0
    with pytest.raises(FrozenInstanceError):
        week.close = 99.0


def test_bar_on_a_non_session_is_rejected() -> None:
    bars = fixture_bars()
    calendar = TradingCalendar(tuple(session for session in fixture_sessions() if session != date(2026, 10, 2)))

    with pytest.raises(StrategyInputError, match="trading session"):
        aggregate_completed_weeks(bars, "forward", calendar, AS_OF_WEDNESDAY)


def test_week_becomes_complete_only_after_its_final_session_close() -> None:
    calendar = TradingCalendar(fixture_sessions())
    before_close = datetime(2026, 10, 2, 14, 59, tzinfo=ZoneInfo("Asia/Shanghai"))
    after_close = datetime(2026, 10, 2, 15, 1, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert calendar.completed_week_ends(before_close) == ()
    assert calendar.completed_week_ends(after_close) == (date(2026, 10, 2),)
