"""Validation and causal aggregation of daily bars into completed weeks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby

from astock_quant.core.errors import StrategyInputError
from astock_quant.core.models import Bar
from astock_quant.data.calendar import TradingCalendar


ADJUSTMENT_BASES = frozenset({"forward", "backward", "unadjusted"})


def _input_error(scope: str, detail: str) -> StrategyInputError:
    return StrategyInputError(
        stage="weekly_bar_aggregation",
        scope=scope,
        source="daily_bars",
        detail=detail,
    )


@dataclass(frozen=True)
class WeeklyBar:
    code: str
    start: datetime
    end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    source: str


def validate_daily_bars(
    bars: Sequence[Bar],
    adjustment_basis: str,
    calendar: TradingCalendar,
    as_of: datetime,
) -> None:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise _input_error("as_of", "as_of must be timezone-aware")
    if adjustment_basis not in ADJUSTMENT_BASES:
        raise _input_error(adjustment_basis, "unsupported or mixed adjustment basis")
    if not bars:
        return

    timestamps = tuple(bar.timestamp for bar in bars)
    if len(timestamps) != len(set(timestamps)):
        raise _input_error(bars[0].code, "daily bars contain duplicate timestamps")
    if any(left >= right for left, right in zip(timestamps, timestamps[1:])):
        raise _input_error(bars[0].code, "daily bars must be strictly increasing")
    if len({bar.code for bar in bars}) != 1:
        raise _input_error("multiple", "daily bars must contain exactly one code")

    sessions = set(calendar.sessions)
    for bar in bars:
        local_date = bar.timestamp.astimezone(calendar.timezone).date()
        if local_date not in sessions:
            raise _input_error(bar.code, f"bar date {local_date.isoformat()} is not a trading session")


def aggregate_completed_weeks(
    bars: Sequence[Bar],
    adjustment_basis: str,
    calendar: TradingCalendar,
    as_of: datetime,
) -> tuple[WeeklyBar, ...]:
    validate_daily_bars(bars, adjustment_basis, calendar, as_of)
    completed = set(calendar.completed_week_ends(as_of))
    visible = tuple(bar for bar in bars if bar.timestamp <= as_of)
    weekly: list[WeeklyBar] = []

    for _, grouped in groupby(
        visible,
        key=lambda bar: bar.timestamp.astimezone(calendar.timezone).date().isocalendar()[:2],
    ):
        week_bars = tuple(grouped)
        last_session = week_bars[-1].timestamp.astimezone(calendar.timezone).date()
        calendar_week_end = next(
            (
                session
                for session in reversed(calendar.sessions)
                if session.isocalendar()[:2] == last_session.isocalendar()[:2]
            ),
            None,
        )
        if calendar_week_end not in completed:
            continue
        weekly.append(
            WeeklyBar(
                code=week_bars[0].code,
                start=week_bars[0].timestamp,
                end=week_bars[-1].timestamp,
                open=week_bars[0].open,
                high=max(bar.high for bar in week_bars),
                low=min(bar.low for bar in week_bars),
                close=week_bars[-1].close,
                volume=sum(bar.volume for bar in week_bars),
                amount=sum(bar.amount for bar in week_bars),
                source=week_bars[0].source,
            )
        )
    return tuple(weekly)
