"""Stable, auditable contracts for weekly-trend strategy evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from math import isfinite

from astock_quant.core.models import Signal


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_price(value: float, name: str) -> None:
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive price")


@dataclass(frozen=True)
class RuleCheck:
    code: str
    passed: bool
    actual: str
    threshold: str
    reason_zh: str

    def __post_init__(self) -> None:
        for name in ("code", "actual", "threshold", "reason_zh"):
            _require_text(getattr(self, name), name)


@dataclass(frozen=True)
class TrendAssessment:
    qualified: bool
    sufficient_data: bool
    checks: tuple[RuleCheck, ...]
    as_of: datetime

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "as_of")
        if self.qualified and not self.sufficient_data:
            raise ValueError("qualified trend requires sufficient_data")


class SetupKind(str, Enum):
    BREAKOUT = "breakout"
    GOLDEN_CROSS = "golden_cross"
    PULLBACK = "pullback"

    @classmethod
    def priority(cls) -> tuple[SetupKind, ...]:
        return (cls.BREAKOUT, cls.GOLDEN_CROSS, cls.PULLBACK)


@dataclass(frozen=True)
class SetupHit:
    kind: SetupKind
    occurred_at: datetime
    reference_price: float
    reference_label: str
    checks: tuple[RuleCheck, ...]

    def __post_init__(self) -> None:
        _require_aware(self.occurred_at, "occurred_at")
        _require_price(self.reference_price, "reference_price")
        _require_text(self.reference_label, "reference_label")


@dataclass(frozen=True)
class SetupAssessment:
    hits: tuple[SetupHit, ...]
    selected: SetupHit | None
    checks: tuple[RuleCheck, ...]
    as_of: datetime

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "as_of")
        if self.selected is not None and self.selected not in self.hits:
            raise ValueError("selected setup must be present in hits")


class PatternStatus(str, Enum):
    INACTIVE = "inactive"
    WAITING_CONFIRMATION = "waiting_confirmation"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    CANCELLED_UNFILLED = "cancelled_unfilled"


@dataclass(frozen=True)
class PatternState:
    code: str
    status: PatternStatus
    setup: SetupHit | None
    created_at: datetime | None
    expires_on: date | None
    emitted_signal_id: str | None
    strategy_version: str
    parameter_version: str
    data_cutoff: datetime

    def __post_init__(self) -> None:
        _require_text(self.code, "code")
        _require_text(self.strategy_version, "strategy_version")
        _require_text(self.parameter_version, "parameter_version")
        _require_aware(self.data_cutoff, "data_cutoff")
        if self.created_at is not None:
            _require_aware(self.created_at, "created_at")
            if self.created_at > self.data_cutoff:
                raise ValueError("created_at cannot be after data_cutoff")

        if self.status is PatternStatus.INACTIVE:
            if any(value is not None for value in (self.setup, self.created_at, self.expires_on, self.emitted_signal_id)):
                raise ValueError("inactive state cannot contain setup lifecycle fields")
            return

        if self.setup is None or self.created_at is None or self.expires_on is None:
            raise ValueError("non-inactive state requires setup, created_at, and expires_on")
        if self.expires_on < self.created_at.date():
            raise ValueError("expires_on cannot precede created_at")
        if self.status in (PatternStatus.CONFIRMED, PatternStatus.CANCELLED_UNFILLED):
            if self.emitted_signal_id is None or not self.emitted_signal_id.strip():
                raise ValueError("confirmed lifecycle requires emitted signal id")
        elif self.emitted_signal_id is not None:
            raise ValueError("unconfirmed lifecycle cannot contain emitted signal id")


@dataclass(frozen=True)
class ConfirmationResult:
    confirmed: bool
    checks: tuple[RuleCheck, ...]
    as_of: datetime
    reason_code: str
    reason_zh: str

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "as_of")
        _require_text(self.reason_code, "reason_code")
        _require_text(self.reason_zh, "reason_zh")


class DecisionAction(str, Enum):
    IGNORE = "ignore"
    WAIT = "wait"
    EMIT_SIGNAL = "emit_signal"
    EXPIRE = "expire"
    INVALIDATE = "invalidate"
    CANCEL_UNFILLED = "cancel_unfilled"


@dataclass(frozen=True)
class StrategyDecision:
    code: str
    evaluated_at: datetime
    data_cutoff: datetime
    strategy_version: str
    parameter_version: str
    trend: TrendAssessment
    setups: SetupAssessment
    confirmation: ConfirmationResult | None
    previous_status: PatternStatus
    next_status: PatternStatus
    expires_on: date | None
    action: DecisionAction
    reason_code: str
    reason_zh: str
    all_checks: tuple[RuleCheck, ...]

    def __post_init__(self) -> None:
        for name in ("code", "strategy_version", "parameter_version", "reason_code", "reason_zh"):
            _require_text(getattr(self, name), name)
        _require_aware(self.evaluated_at, "evaluated_at")
        _require_aware(self.data_cutoff, "data_cutoff")
        if self.data_cutoff > self.evaluated_at:
            raise ValueError("data_cutoff cannot be after evaluated_at")


@dataclass(frozen=True)
class StrategyEvaluation:
    signal: Signal | None
    decision: StrategyDecision
    next_state: PatternState
    initial_stop: float | None

    def __post_init__(self) -> None:
        if self.initial_stop is not None:
            _require_price(self.initial_stop, "initial_stop")
        if self.next_state.code != self.decision.code:
            raise ValueError("decision and next_state codes must match")
