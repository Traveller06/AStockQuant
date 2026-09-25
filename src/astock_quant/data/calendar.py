"""Explicit exchange-session calendar used by causal strategy calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from itertools import groupby
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


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
