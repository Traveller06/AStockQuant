import json
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from astock_quant.strategies.weekly_trend.config import WeeklyTrendConfig
from astock_quant.strategies.weekly_trend.models import (
    ConfirmationResult,
    DecisionAction,
    PatternState,
    PatternStatus,
    RuleCheck,
    SetupAssessment,
    SetupHit,
    SetupKind,
    StrategyDecision,
    StrategyEvaluation,
    TrendAssessment,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 25, 15, 0, tzinfo=SHANGHAI)


def _check() -> RuleCheck:
    return RuleCheck(
        code="trend.ma_order",
        passed=True,
        actual="MA5W=12.1, MA10W=11.8, MA20W=11.0",
        threshold="MA5W > MA10W > MA20W",
        reason_zh="周均线保持多头排列",
    )


def _setup() -> SetupHit:
    return SetupHit(
        kind=SetupKind.BREAKOUT,
        occurred_at=NOW,
        reference_price=12.5,
        reference_label="前高",
        checks=(_check(),),
    )


def _state(status: PatternStatus = PatternStatus.WAITING_CONFIRMATION) -> PatternState:
    setup = None if status is PatternStatus.INACTIVE else _setup()
    return PatternState(
        code="600000",
        status=status,
        setup=setup,
        created_at=None if setup is None else NOW,
        expires_on=None if setup is None else date(2026, 10, 23),
        emitted_signal_id="sig-1" if status is PatternStatus.CONFIRMED else None,
        strategy_version="1.0.0",
        parameter_version="weekly-trend-v1",
        data_cutoff=NOW,
    )


def test_default_configuration_matches_approved_spec() -> None:
    config = WeeklyTrendConfig()
    assert config.strategy_id == "weekly_trend_confirmation"
    assert config.strategy_version == "1.0.0"
    assert config.parameter_version == "weekly-trend-v1"
    assert config.weekly_ma_periods == (5, 10, 20)
    assert config.breakout_volume_multiple == Decimal("1.5")
    assert config.support_tolerance == Decimal("0.03")
    assert config.setup_valid_sessions == 20
    assert config.stabilization_low_tolerance == Decimal("0.01")
    assert config.daily_volume_multiple == Decimal("1.3")


def test_configuration_is_immutable_and_rejects_invalid_thresholds() -> None:
    with pytest.raises(FrozenInstanceError):
        WeeklyTrendConfig().setup_valid_sessions = 10
    with pytest.raises(ValueError, match="positive"):
        WeeklyTrendConfig(setup_valid_sessions=0)
    with pytest.raises(ValueError, match="increasing"):
        WeeklyTrendConfig(weekly_ma_periods=(10, 5, 20))
    with pytest.raises(ValueError, match="tolerance"):
        WeeklyTrendConfig(support_tolerance=Decimal("1"))


def test_manifest_parameters_are_json_safe_and_preserve_decimal_text() -> None:
    parameters = WeeklyTrendConfig().to_manifest_parameters()
    assert parameters["breakout_volume_multiple"] == "1.5"
    assert parameters["weekly_ma_periods"] == [5, 10, 20]
    json.dumps(parameters)


def test_setup_priority_and_pattern_status_values_are_stable() -> None:
    assert SetupKind.priority() == (
        SetupKind.BREAKOUT,
        SetupKind.GOLDEN_CROSS,
        SetupKind.PULLBACK,
    )
    assert [item.value for item in PatternStatus] == [
        "inactive",
        "waiting_confirmation",
        "confirmed",
        "expired",
        "invalidated",
        "cancelled_unfilled",
    ]


def test_rule_check_requires_non_empty_stable_explanation_fields() -> None:
    with pytest.raises(ValueError, match="reason_zh"):
        RuleCheck(code="trend.ma_order", passed=False, actual="10", threshold="20", reason_zh="")
    with pytest.raises(ValueError, match="code"):
        replace(_check(), code=" ")


def test_public_models_are_frozen_and_validate_times_and_reference_prices() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(_setup(), occurred_at=datetime(2026, 9, 25, 15, 0))
    with pytest.raises(ValueError, match="positive"):
        replace(_setup(), reference_price=float("nan"))
    with pytest.raises(FrozenInstanceError):
        _setup().reference_price = 99.0


def test_pattern_state_enforces_consistent_status_fields() -> None:
    _state()
    _state(PatternStatus.INACTIVE)
    _state(PatternStatus.CONFIRMED)

    with pytest.raises(ValueError, match="setup"):
        replace(_state(), setup=None)
    with pytest.raises(ValueError, match="signal"):
        replace(_state(PatternStatus.CONFIRMED), emitted_signal_id=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(_state(), data_cutoff=datetime(2026, 9, 25, 15, 0))


def test_assessments_decision_and_evaluation_share_auditable_contracts() -> None:
    check = _check()
    setup = _setup()
    trend = TrendAssessment(True, True, (check,), NOW)
    setups = SetupAssessment((setup,), setup, (check,), NOW)
    confirmation = ConfirmationResult(True, (check,), NOW, "confirm.ok", "日线确认通过")
    state = _state(PatternStatus.CONFIRMED)
    decision = StrategyDecision(
        code="600000",
        evaluated_at=NOW,
        data_cutoff=NOW,
        strategy_version="1.0.0",
        parameter_version="weekly-trend-v1",
        trend=trend,
        setups=setups,
        confirmation=confirmation,
        previous_status=PatternStatus.WAITING_CONFIRMATION,
        next_status=PatternStatus.CONFIRMED,
        expires_on=state.expires_on,
        action=DecisionAction.EMIT_SIGNAL,
        reason_code="decision.confirmed",
        reason_zh="日线确认通过，发出下一交易日买入意图",
        all_checks=(check,),
    )
    evaluation = StrategyEvaluation(None, decision, state, 10.8)

    assert evaluation.decision.all_checks == (check,)
    assert evaluation.next_state.status is PatternStatus.CONFIRMED
    assert evaluation.initial_stop == 10.8

    with pytest.raises(ValueError, match="reason_zh"):
        replace(decision, reason_zh="")
    with pytest.raises(ValueError, match="finite positive"):
        replace(evaluation, initial_stop=0.0)
