"""Deterministic event loop connecting strategy, matcher, and portfolio."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Callable, Mapping, Protocol, Sequence
from uuid import NAMESPACE_URL, uuid4, uuid5

from astock_quant.core.enums import Market, OrderStatus, Side
from astock_quant.core.models import Bar, Order, Signal, Trade
from astock_quant.data.calendar import TradingCalendar
from astock_quant.strategies.weekly_trend.models import PatternState, PatternStatus

from .fees import FeeSchedule
from .matcher import match_next_session
from .models import ExecutionBar, LedgerPosition, MatchStatus, PortfolioSnapshot
from .portfolio import PortfolioLedger


class ReconciliationError(RuntimeError):
    """Raised when cash, positions, fees, and equity do not reconcile."""


class StrategyLike(Protocol):
    strategy_id: str
    strategy_version: str
    config: object

    def evaluate(self, **kwargs: object) -> object: ...


@dataclass(frozen=True)
class BacktestRequest:
    daily_bars: Mapping[str, tuple[Bar, ...]]
    execution_bars: Mapping[str, tuple[ExecutionBar, ...]]
    calendar: TradingCalendar
    initial_cash: Decimal
    fees: FeeSchedule
    adjustment_basis: str
    data_as_of: date
    app_version: str
    max_position_fraction: Decimal = Decimal("0.20")
    run_id: str | None = None

    def __post_init__(self) -> None:
        if not self.adjustment_basis.strip():
            raise ValueError("adjustment_basis must not be empty")
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if not Decimal("0") < self.max_position_fraction <= Decimal("1"):
            raise ValueError("max_position_fraction must be in (0, 1]")
        if self.data_as_of > self.calendar.sessions[-1]:
            raise ValueError("data_as_of cannot be after the calendar")


@dataclass(frozen=True)
class BacktestEvent:
    code: str
    symbol: str
    occurred_at: datetime
    reason_zh: str
    signal_id: str | None = None


@dataclass(frozen=True)
class EquityPoint:
    session: date
    cash: Decimal
    equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_fees: Decimal
    position_count: int


@dataclass(frozen=True)
class BacktestResult:
    run_id: str
    signals: tuple[Signal, ...]
    orders: tuple[Order, ...]
    trades: tuple[Trade, ...]
    decisions: tuple[object, ...]
    checks: tuple[object, ...]
    events: tuple[BacktestEvent, ...]
    errors: tuple[Mapping[str, str], ...]
    snapshots: tuple[EquityPoint, ...]
    reconciled: bool

    def reconciles_to_cent(self) -> bool:
        return self.reconciled


@dataclass
class _Pending:
    order_index: int
    signal: Signal
    requested_shares: int
    stop: Decimal | None


def _order_id(signal: Signal, side: Side) -> str:
    return str(uuid5(NAMESPACE_URL, f"{signal.signal_id}|{side.value}|order"))


def _trade_id(order: Order, traded_at: datetime) -> str:
    return str(uuid5(NAMESPACE_URL, f"{order.order_id}|{traded_at.isoformat()}|trade"))


def _market(code: str) -> Market:
    return Market.SSE if code.startswith("6") else Market.SZSE


def _inactive_state(code: str, cutoff: datetime, strategy: StrategyLike) -> PatternState:
    config = strategy.config
    return PatternState(
        code=code,
        status=PatternStatus.INACTIVE,
        setup=None,
        created_at=None,
        expires_on=None,
        emitted_signal_id=None,
        strategy_version=strategy.strategy_version,
        parameter_version=str(getattr(config, "parameter_version")),
        data_cutoff=cutoff,
    )


class BacktestEngine:
    def __init__(self, strategy: StrategyLike) -> None:
        self.strategy = strategy

    def run(self, request: BacktestRequest) -> BacktestResult:
        run_id = request.run_id or str(uuid4())
        ledger = PortfolioLedger(initial_cash=request.initial_cash, fees=request.fees)
        daily_by_date = {
            symbol: {bar.timestamp.date(): bar for bar in bars}
            for symbol, bars in request.daily_bars.items()
        }
        execution_by_date = {
            symbol: {item.bar.timestamp.date(): item for item in bars}
            for symbol, bars in request.execution_bars.items()
        }
        states = {
            symbol: _inactive_state(symbol, bars[0].timestamp, self.strategy)
            for symbol, bars in request.daily_bars.items()
            if bars
        }
        signals: list[Signal] = []
        orders: list[Order] = []
        trades: list[Trade] = []
        decisions: list[object] = []
        checks: list[object] = []
        events: list[BacktestEvent] = []
        errors: list[Mapping[str, str]] = []
        snapshots: list[EquityPoint] = []
        pending_entries: dict[str, _Pending] = {}
        pending_exits: dict[str, _Pending] = {}
        stops: dict[str, Decimal] = {}
        entry_signal_by_symbol: dict[str, Signal] = {}
        last_marks: dict[str, Decimal] = {}
        failed_symbols: set[str] = set()
        reconciled = True

        for session in request.calendar.sessions:
            if session > request.data_as_of:
                break
            self._match_pending(
                session,
                request,
                execution_by_date,
                ledger,
                orders,
                trades,
                events,
                pending_exits,
                pending_entries,
                stops,
                entry_signal_by_symbol,
            )

            for symbol in sorted(request.daily_bars):
                bar = daily_by_date.get(symbol, {}).get(session)
                if bar is None:
                    continue
                last_marks[symbol] = Decimal(str(bar.close))
                if symbol in ledger.positions and symbol not in pending_exits:
                    stop = stops.get(symbol)
                    if stop is not None and Decimal(str(bar.low)) <= stop:
                        source = entry_signal_by_symbol[symbol]
                        exit_signal = replace(
                            source,
                            timestamp=bar.timestamp,
                            side=Side.SELL,
                            reason="盘中触及初始止损，下一交易日退出",
                        )
                        order = self._new_order(exit_signal, ledger.positions[symbol].shares, float(stop))
                        orders.append(order)
                        pending_exits[symbol] = _Pending(len(orders) - 1, exit_signal, order.quantity, stop)

                if symbol in failed_symbols:
                    continue
                visible = tuple(item for item in request.daily_bars[symbol] if item.timestamp <= bar.timestamp)
                minimum_bars = int(
                    getattr(
                        self.strategy,
                        "minimum_bars",
                        max(getattr(self.strategy.config, "weekly_ma_periods", (20,))) * 5,
                    )
                )
                if len(visible) < minimum_bars:
                    continue
                try:
                    evaluation = self.strategy.evaluate(
                        source_run_id=run_id,
                        daily_bars=visible,
                        adjustment_basis=request.adjustment_basis,
                        calendar=request.calendar,
                        as_of=bar.timestamp,
                        state=states[symbol],
                    )
                except Exception as exc:
                    failed_symbols.add(symbol)
                    errors.append(
                        {
                            "stage": "strategy_evaluation",
                            "symbol": symbol,
                            "error": str(exc),
                        }
                    )
                    continue
                states[symbol] = evaluation.next_state
                decisions.append(evaluation.decision)
                checks.extend(getattr(evaluation.decision, "all_checks", ()))
                signal = evaluation.signal
                if signal is None or symbol in ledger.positions or symbol in pending_entries:
                    continue
                budget = request.initial_cash * request.max_position_fraction
                requested = int(budget / Decimal(str(bar.close))) // 100 * 100
                if requested <= 0:
                    events.append(BacktestEvent("portfolio.insufficient_cash", symbol, bar.timestamp, "资金不足一手"))
                    continue
                signals.append(signal)
                entry_signal_by_symbol[symbol] = signal
                order = self._new_order(signal, requested, bar.close)
                orders.append(order)
                pending_entries[symbol] = _Pending(
                    len(orders) - 1,
                    signal,
                    requested,
                    Decimal(str(evaluation.initial_stop)) if evaluation.initial_stop is not None else None,
                )

            marks = {symbol: price for symbol, price in last_marks.items() if symbol in ledger.positions}
            snapshot = ledger.snapshot(mark_prices=marks)
            reconciled = reconciled and ledger.reconciles_to_cent(mark_prices=marks)
            snapshots.append(self._equity_point(session, snapshot))

        return BacktestResult(
            run_id=run_id,
            signals=tuple(signals),
            orders=tuple(orders),
            trades=tuple(trades),
            decisions=tuple(decisions),
            checks=tuple(checks),
            events=tuple(events),
            errors=tuple(errors),
            snapshots=tuple(snapshots),
            reconciled=reconciled,
        )

    def _match_pending(
        self,
        session: date,
        request: BacktestRequest,
        execution_by_date: Mapping[str, Mapping[date, ExecutionBar]],
        ledger: PortfolioLedger,
        orders: list[Order],
        trades: list[Trade],
        events: list[BacktestEvent],
        pending_exits: dict[str, _Pending],
        pending_entries: dict[str, _Pending],
        stops: dict[str, Decimal],
        entry_signal_by_symbol: dict[str, Signal],
    ) -> None:
        for symbol, pending in tuple(pending_exits.items()):
            execution = execution_by_date.get(symbol, {}).get(session)
            if execution is None:
                continue
            result = match_next_session(pending.signal, execution, ledger.positions.get(symbol))
            if result.status is MatchStatus.FILLED and result.trade is not None:
                fill = ledger.apply_fill(result.trade, pending.requested_shares)
                orders[pending.order_index] = replace(
                    orders[pending.order_index], status=OrderStatus.FILLED, filled_quantity=fill.shares
                )
                trades.append(self._core_trade(orders[pending.order_index], fill))
                pending_exits.pop(symbol)
                stops.pop(symbol, None)
                entry_signal_by_symbol.pop(symbol, None)
            else:
                events.append(
                    BacktestEvent(result.reason_code, symbol, execution.bar.timestamp, "退出受限，顺延到下一交易日", pending.signal.signal_id)
                )

        for symbol, pending in tuple(pending_entries.items()):
            if session <= pending.signal.timestamp.date():
                continue
            execution = execution_by_date.get(symbol, {}).get(session)
            if execution is None:
                orders[pending.order_index] = replace(orders[pending.order_index], status=OrderStatus.CANCELLED)
                events.append(
                    BacktestEvent("match.missing_execution_entry", symbol, pending.signal.timestamp, "下一交易日缺少成交数据，取消入场", pending.signal.signal_id)
                )
                pending_entries.pop(symbol)
                continue
            result = match_next_session(pending.signal, execution, None)
            if result.status is MatchStatus.FILLED and result.trade is not None:
                fill = ledger.apply_fill(result.trade, pending.requested_shares)
                if fill.shares:
                    orders[pending.order_index] = replace(
                        orders[pending.order_index], status=OrderStatus.FILLED, filled_quantity=fill.shares
                    )
                    trades.append(self._core_trade(orders[pending.order_index], fill))
                    if pending.stop is not None:
                        stops[symbol] = pending.stop
                else:
                    orders[pending.order_index] = replace(orders[pending.order_index], status=OrderStatus.REJECTED)
                    events.append(
                        BacktestEvent("portfolio.insufficient_cash", symbol, execution.bar.timestamp, "可用资金不足一手", pending.signal.signal_id)
                    )
            else:
                orders[pending.order_index] = replace(orders[pending.order_index], status=OrderStatus.CANCELLED)
                events.append(
                    BacktestEvent(result.reason_code, symbol, execution.bar.timestamp, "入场不可成交，按规则取消", pending.signal.signal_id)
                )
            pending_entries.pop(symbol)

    @staticmethod
    def _new_order(signal: Signal, quantity: int, limit_price: float) -> Order:
        return Order(
            order_id=_order_id(signal, signal.side),
            source_run_id=signal.source_run_id,
            broker_id="backtest",
            code=signal.code,
            market=_market(signal.code),
            side=signal.side,
            quantity=quantity,
            limit_price=float(limit_price),
            status=OrderStatus.NEW,
            created_at=signal.timestamp,
            filled_quantity=0,
            signal_id=signal.signal_id,
        )

    @staticmethod
    def _core_trade(order: Order, fill: object) -> Trade:
        return Trade(
            trade_id=_trade_id(order, fill.traded_at),
            order_id=order.order_id,
            source_run_id=order.source_run_id,
            broker_id=order.broker_id,
            code=order.code,
            side=order.side,
            quantity=fill.shares,
            price=float(fill.price),
            commission=float(fill.fees.commission),
            stamp_tax=float(fill.fees.stamp_tax),
            slippage=float(fill.fees.slippage),
            traded_at=fill.traded_at,
            signal_id=order.signal_id or "",
        )

    @staticmethod
    def _equity_point(session: date, snapshot: PortfolioSnapshot) -> EquityPoint:
        return EquityPoint(
            session=session,
            cash=snapshot.cash,
            equity=snapshot.equity,
            realized_pnl=snapshot.realized_pnl,
            unrealized_pnl=snapshot.unrealized_pnl,
            total_fees=snapshot.total_fees,
            position_count=len(snapshot.positions),
        )
