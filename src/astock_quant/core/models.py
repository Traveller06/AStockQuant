"""Immutable value objects used across data, strategy, and broker layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Mapping, TypeAlias
from uuid import NAMESPACE_URL, uuid4, uuid5

from .enums import Market, OrderStatus, RunStatus, Side


JSONValue: TypeAlias = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]


@dataclass(frozen=True)
class Instrument:
    code: str
    name: str
    market: Market
    board: str
    is_listed: bool


@dataclass(frozen=True)
class Bar:
    code: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    source: str

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("Bar timestamp must be timezone-aware")
        if not all(isfinite(price) and price > 0 for price in (self.open, self.high, self.low, self.close)):
            raise ValueError("OHLC prices must be positive")
        if not isfinite(self.volume) or self.volume < 0:
            raise ValueError("volume must be non-negative")
        if not isfinite(self.amount) or self.amount < 0:
            raise ValueError("amount must be non-negative")
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("OHLC values are inconsistent")


@dataclass(frozen=True)
class QuoteSnapshot:
    code: str
    price: float
    change_pct: float
    amplitude_pct: float
    turnover_pct: float
    float_market_cap: float
    timestamp: datetime


@dataclass(frozen=True)
class Signal:
    signal_id: str
    source_run_id: str
    strategy_id: str
    code: str
    timestamp: datetime
    side: Side
    strength: float
    reason: str
    parameter_version: str

    @classmethod
    def new(
        cls,
        *,
        source_run_id: str,
        strategy_id: str,
        code: str,
        timestamp: datetime,
        side: Side,
        strength: float,
        reason: str,
        parameter_version: str,
    ) -> Signal:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Signal timestamp must be timezone-aware")
        for value, name in (
            (source_run_id, "source_run_id"),
            (strategy_id, "strategy_id"),
            (code, "code"),
            (reason, "reason"),
            (parameter_version, "parameter_version"),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be empty")
        if not isfinite(strength) or strength < 0:
            raise ValueError("strength must be finite and non-negative")
        identity = "|".join(
            (
                source_run_id,
                strategy_id,
                code,
                timestamp.isoformat(),
                side.value,
                parameter_version,
            )
        )
        return cls(
            signal_id=str(uuid5(NAMESPACE_URL, identity)),
            source_run_id=source_run_id,
            strategy_id=strategy_id,
            code=code,
            timestamp=timestamp,
            side=side,
            strength=strength,
            reason=reason,
            parameter_version=parameter_version,
        )


@dataclass(frozen=True)
class Order:
    order_id: str
    source_run_id: str
    broker_id: str
    code: str
    market: Market
    side: Side
    quantity: int
    limit_price: float
    status: OrderStatus
    created_at: datetime
    filled_quantity: int
    signal_id: str | None = None

    @classmethod
    def new(
        cls,
        source_run_id: str,
        broker_id: str,
        code: str,
        market: Market,
        side: Side,
        quantity: int,
        limit_price: float,
        *,
        signal_id: str | None = None,
    ) -> Order:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if quantity % 100:
            raise ValueError("quantity must be divisible by 100 for A-share stock orders")
        if not isfinite(limit_price) or limit_price <= 0:
            raise ValueError("limit_price must be positive")
        return cls(
            order_id=str(uuid4()),
            source_run_id=source_run_id,
            broker_id=broker_id,
            code=code,
            market=market,
            side=side,
            quantity=quantity,
            limit_price=limit_price,
            status=OrderStatus.NEW,
            created_at=datetime.now(timezone.utc),
            filled_quantity=0,
            signal_id=signal_id,
        )


@dataclass(frozen=True)
class Trade:
    trade_id: str
    order_id: str
    source_run_id: str
    broker_id: str
    code: str
    side: Side
    quantity: int
    price: float
    commission: float
    stamp_tax: float
    slippage: float
    traded_at: datetime
    signal_id: str


@dataclass(frozen=True)
class Position:
    code: str
    quantity: int
    available_quantity: int
    average_cost: float
    last_price: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float


@dataclass(frozen=True)
class AccountSnapshot:
    broker_id: str
    cash: float
    equity: float
    peak_equity: float
    positions: Mapping[str, Position]
    timestamp: datetime
    risk_state: str


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    app_version: str
    strategy_id: str
    strategy_version: str
    parameters: Mapping[str, JSONValue]
    sample_sha256: str
    data_cutoff: str
    data_sha256: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    errors: tuple[Mapping[str, JSONValue], ...] = ()
