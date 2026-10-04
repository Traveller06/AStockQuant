"""Explicit exchange-session calendar used by causal strategy calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from itertools import groupby
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


# SSE official 2026 closure notice, also shared by SZSE/BSE:
# https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml
# Other years retain the historical weekday fallback until their notices are added.
HOLIDAY_RANGES_2026 = (
    (date(2026, 1, 1), date(2026, 1, 3)),
    (date(2026, 2, 15), date(2026, 2, 23)),
    (date(2026, 4, 4), date(2026, 4, 6)),
    (date(2026, 5, 1), date(2026, 5, 5)),
    (date(2026, 6, 19), date(2026, 6, 21)),
    (date(2026, 9, 25), date(2026, 9, 27)),
    (date(2026, 10, 1), date(2026, 10, 7)),
)


def previous_open_day(cutoff: date) -> date:
    """Return the open weekday on/before cutoff using the published 2026 schedule.

    This is the live-screen default only; explicit historical session calendars
    remain the source of truth for backtests. Make-up weekend workdays stay closed.
    """
    while cutoff.weekday() >= 5 or any(start <= cutoff <= end for start, end in HOLIDAY_RANGES_2026):
        cutoff -= timedelta(days=1)
    return cutoff


@dataclass(frozen=True)
class TradingCalendar:
    sessions: tuple[date, ...]
    timezone: ZoneInfo = SHANGHAI
    session_close: time = time(15, 0)

    def __post_init__(self) -> None:
        if len(self.sessions) != len(set(self.sessions)):
            raise ValueError("calendar sessions contain duplicate dates")
        if any(left >= right for left, right in zip(self.sessions, self.sessions[1:])):
            raise ValueError("calendar sessions must be strictly increasing")

    def completed_week_ends(self, as_of: datetime) -> tuple[date, ...]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        local_cutoff = as_of.astimezone(self.timezone)
        week_ends: list[date] = []
        for _, grouped in groupby(self.sessions, key=lambda session: session.isocalendar()[:2]):
            week_end = tuple(grouped)[-1]
            close = datetime.combine(week_end, self.session_close, tzinfo=self.timezone)
            if local_cutoff >= close:
                week_ends.append(week_end)
        return tuple(week_ends)
