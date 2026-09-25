"""Deterministic lifecycle for weekly setup confirmation states."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime, time

from .config import WeeklyTrendConfig
from .models import (
    ConfirmationResult,
    PatternState,
    PatternStatus,
    SetupHit,
    SetupKind,
    TrendAssessment,
)


TERMINAL_STATUSES = frozenset(
    {
        PatternStatus.CONFIRMED,
        PatternStatus.EXPIRED,
        PatternStatus.INVALIDATED,
        PatternStatus.CANCELLED_UNFILLED,
    }
)


def _cutoff(state: PatternState, session: date) -> datetime:
    return datetime.combine(session, time(15, 0), tzinfo=state.data_cutoff.tzinfo)


def _priority(kind: SetupKind) -> int:
    return SetupKind.priority().index(kind)


def _replacement_expiry(
    setup: SetupHit,
    calendar_sessions: Sequence[date],
    valid_sessions: int,
) -> date:
    later = tuple(session for session in calendar_sessions if session > setup.occurred_at.date())
    if len(later) < valid_sessions:
        raise ValueError("calendar_sessions do not cover the replacement setup validity window")
    return later[valid_sessions - 1]


def advance_state(
    state: PatternState,
    session: date,
    trend: TrendAssessment,
    confirmation: ConfirmationResult,
    new_setup: SetupHit | None = None,
    *,
    calendar_sessions: Sequence[date] = (),
    config: WeeklyTrendConfig | None = None,
    signal_id: str | None = None,
) -> PatternState:
    """Advance one state in the documented transition priority order."""

    if state.status in TERMINAL_STATUSES:
        return state
    if state.status is not PatternStatus.WAITING_CONFIRMATION or state.setup is None:
        return state

    cutoff = _cutoff(state, session)
    if not trend.qualified or not trend.sufficient_data:
        return replace(state, status=PatternStatus.INVALIDATED, data_cutoff=cutoff)
    if state.expires_on is not None and session > state.expires_on:
        return replace(state, status=PatternStatus.EXPIRED, data_cutoff=cutoff)

    if new_setup is not None and _priority(new_setup.kind) < _priority(state.setup.kind):
        settings = config or WeeklyTrendConfig()
        expires_on = _replacement_expiry(
            new_setup,
            calendar_sessions,
            settings.setup_valid_sessions,
        )
        return PatternState(
            code=state.code,
            status=PatternStatus.WAITING_CONFIRMATION,
            setup=new_setup,
            created_at=new_setup.occurred_at,
            expires_on=expires_on,
            emitted_signal_id=None,
            strategy_version=state.strategy_version,
            parameter_version=state.parameter_version,
            data_cutoff=cutoff,
        )

    if confirmation.confirmed:
        emitted = signal_id or (
            f"{state.strategy_version}:{state.parameter_version}:{state.code}:{session.isoformat()}:buy"
        )
        if not emitted.strip():
            raise ValueError("signal_id must not be empty")
        return replace(
            state,
            status=PatternStatus.CONFIRMED,
            emitted_signal_id=emitted,
            data_cutoff=cutoff,
        )
    return state


def mark_entry_unfilled(state: PatternState, session: date) -> PatternState:
    """Cancel a confirmed entry once without altering other lifecycle states."""

    if state.status is not PatternStatus.CONFIRMED:
        return state
    return replace(
        state,
        status=PatternStatus.CANCELLED_UNFILLED,
        data_cutoff=_cutoff(state, session),
    )
