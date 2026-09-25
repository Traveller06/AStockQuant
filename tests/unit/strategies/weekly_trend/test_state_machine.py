from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from astock_quant.strategies.weekly_trend.models import (
    ConfirmationResult,
    PatternState,
    PatternStatus,
    RuleCheck,
    SetupHit,
    SetupKind,
    TrendAssessment,
)
from astock_quant.strategies.weekly_trend.state_machine import advance_state, mark_entry_unfilled


SHANGHAI = ZoneInfo("Asia/Shanghai")
CREATED = datetime(2026, 9, 4, 15, 0, tzinfo=SHANGHAI)
SESSIONS = tuple(date(2026, 9, 7) + timedelta(days=index) for index in range(25))


def _setup(kind: SetupKind = SetupKind.PULLBACK, occurred_at: datetime = CREATED) -> SetupHit:
    return SetupHit(kind, occurred_at, 10.0, "测试参考位", ())


def _state(kind: SetupKind = SetupKind.PULLBACK) -> PatternState:
    return PatternState(
        code="600000",
        status=PatternStatus.WAITING_CONFIRMATION,
        setup=_setup(kind),
        created_at=CREATED,
        expires_on=SESSIONS[19],
        emitted_signal_id=None,
        strategy_version="1.0.0",
        parameter_version="weekly-trend-v1",
        data_cutoff=CREATED,
    )


def _trend(qualified: bool = True) -> TrendAssessment:
    check = RuleCheck("trend.fixture", qualified, str(qualified), "true", "趋势测试结果")
    return TrendAssessment(qualified, True, (check,), CREATED)


def _confirmation(confirmed: bool = False) -> ConfirmationResult:
    check = RuleCheck("confirm.fixture", confirmed, str(confirmed), "true", "确认测试结果")
    return ConfirmationResult(confirmed, (check,), CREATED, "confirm.fixture", "确认测试结果")


def test_setup_expires_after_twenty_trading_sessions() -> None:
    state = _state()

    assert advance_state(state, SESSIONS[19], _trend(), _confirmation()).status is PatternStatus.WAITING_CONFIRMATION
    assert advance_state(state, SESSIONS[20], _trend(), _confirmation()).status is PatternStatus.EXPIRED


def test_trend_break_invalidates_immediately() -> None:
    result = advance_state(_state(), SESSIONS[3], _trend(False), _confirmation())
    assert result.status is PatternStatus.INVALIDATED


def test_higher_priority_setup_replaces_lower_priority_state() -> None:
    replacement_time = datetime(2026, 9, 11, 15, 0, tzinfo=SHANGHAI)
    breakout = _setup(SetupKind.BREAKOUT, replacement_time)

    result = advance_state(
        _state(SetupKind.PULLBACK),
        date(2026, 9, 11),
        _trend(),
        _confirmation(),
        breakout,
        calendar_sessions=SESSIONS,
    )

    assert result.setup is breakout
    assert result.created_at == replacement_time
    assert result.expires_on == SESSIONS[24]


def test_equal_or_lower_priority_setup_does_not_replace_current_state() -> None:
    state = _state(SetupKind.GOLDEN_CROSS)
    assert advance_state(state, SESSIONS[2], _trend(), _confirmation(), _setup(SetupKind.PULLBACK)) == state


def test_confirmation_emits_once_and_terminal_state_is_noop() -> None:
    confirmed = advance_state(
        _state(),
        SESSIONS[2],
        _trend(),
        _confirmation(True),
        signal_id="sig-1",
    )

    assert confirmed.status is PatternStatus.CONFIRMED
    assert confirmed.emitted_signal_id == "sig-1"
    assert advance_state(confirmed, SESSIONS[3], _trend(), _confirmation(True), signal_id="sig-2") == confirmed


def test_unfilled_entry_can_only_cancel_confirmed_state() -> None:
    confirmed = advance_state(_state(), SESSIONS[2], _trend(), _confirmation(True), signal_id="sig-1")
    cancelled = mark_entry_unfilled(confirmed, SESSIONS[3])

    assert cancelled.status is PatternStatus.CANCELLED_UNFILLED
    assert cancelled.emitted_signal_id == "sig-1"
    assert mark_entry_unfilled(_state(), SESSIONS[3]) == _state()
