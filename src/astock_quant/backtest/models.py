"""Immutable contracts shared by matching, accounting, and audit layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Mapping

from astock_quant.core.enums import Side
from astock_quant.core.models import Bar

if TYPE_CHECKING:
    from .fees import FeeBreakdown


def as_decimal(value: Decimal | int | float | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class ExecutionBar:
    bar: Bar
    is_suspended: bool = False
    at_limit_up: bool = False
    at_limit_down: bool = False

    def __post_init__(self) -> None:
        if self.at_limit_up and self.at_limit_down:
            raise ValueError("execution bar cannot be at both limit up and limit down")


@dataclass(frozen=True)
class LedgerPosition:
    code: str
    shares: int
    average_cost: Decimal | str
    opened_at: datetime

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("position code must not be empty")
        if self.shares <= 0 or self.shares % 100:
            raise ValueError("position shares must be a positive board lot")
        if self.opened_at.tzinfo is None or self.opened_at.utcoffset() is None:
            raise ValueError("position opened_at must be timezone-aware")
        cost = as_decimal(self.average_cost)
        if cost <= 0:
            raise ValueError("position average_cost must be positive")
        object.__setattr__(self, "average_cost", cost)


class MatchStatus(str, Enum):
    FILLED = "filled"
    PENDING_ENTRY = "pending_entry"
    CANCELLED_ENTRY = "cancelled_entry"
    PENDING_EXIT = "pending_exit"
    REJECTED = "rejected"


@dataclass(frozen=True)
class MatchedTrade:
    code: str
    side: Side
    price: Decimal
    traded_at: datetime
    signal_id: str


@dataclass(frozen=True)
class MatchResult:
    status: MatchStatus
    reason_code: str
    trade: MatchedTrade | None = None

    @classmethod
    def pending_entry(cls, reason_code: str) -> MatchResult:
        return cls(MatchStatus.PENDING_ENTRY, reason_code)

    @classmethod
    def cancelled_entry(cls, reason_code: str) -> MatchResult:
        return cls(MatchStatus.CANCELLED_ENTRY, reason_code)

    @classmethod
    def pending_exit(cls, reason_code: str) -> MatchResult:
        return cls(MatchStatus.PENDING_EXIT, reason_code)

    @classmethod
    def rejected(cls, reason_code: str) -> MatchResult:
        return cls(MatchStatus.REJECTED, reason_code)


@dataclass(frozen=True)
class PortfolioFill:
    symbol: str
    side: Side
    shares: int
    price: Decimal
    traded_at: datetime
    fees: FeeBreakdown


@dataclass(frozen=True)
class PortfolioSnapshot:
    cash: Decimal
    equity: Decimal
    positions: Mapping[str, LedgerPosition] = field(default_factory=dict)
    realized_pnl: Decimal = Decimal("0.00")
    unrealized_pnl: Decimal = Decimal("0.00")
    total_fees: Decimal = Decimal("0.00")
