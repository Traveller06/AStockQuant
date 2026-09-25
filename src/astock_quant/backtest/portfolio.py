"""Decimal-based cash and position ledger for deterministic backtests."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from astock_quant.core.enums import Side

from .fees import FeeBreakdown, FeeSchedule
from .models import LedgerPosition, MatchedTrade, PortfolioFill, PortfolioSnapshot, as_decimal


class InsufficientPosition(ValueError):
    """Raised when an exit asks for more shares than the account owns."""


class PortfolioLedger:
    def __init__(self, *, initial_cash: Decimal | int | float | str, fees: FeeSchedule) -> None:
        cash = fees.quantize_money(initial_cash)
        if cash <= 0:
            raise ValueError("initial_cash must be positive")
        self.initial_cash = cash
        self.cash = cash
        self.fees = fees
        self.positions: dict[str, LedgerPosition] = {}
        self.realized_pnl = Decimal("0.00")
        self.total_fees = Decimal("0.00")

    @staticmethod
    def _board_lot(shares: int) -> int:
        if shares < 0:
            raise ValueError("requested_shares must not be negative")
        return shares // 100 * 100

    def buy(
        self,
        symbol: str,
        price: Decimal | int | float | str,
        requested_shares: int,
        traded_at: datetime,
    ) -> PortfolioFill:
        raw_price = as_decimal(price)
        shares = self._board_lot(requested_shares)
        fee = self.fees.calculate(side=Side.BUY, price=raw_price, shares=shares)
        while shares and self.fees.quantize_money(raw_price * shares + fee.total) > self.cash:
            shares -= 100
            fee = self.fees.calculate(side=Side.BUY, price=raw_price, shares=shares)
        if not shares:
            return PortfolioFill(symbol, Side.BUY, 0, raw_price, traded_at, FeeBreakdown.zero())

        gross = self.fees.quantize_money(raw_price * shares)
        self.cash = self.fees.quantize_money(self.cash - gross - fee.total)
        self.total_fees = self.fees.quantize_money(self.total_fees + fee.total)
        previous = self.positions.get(symbol)
        if previous is None:
            updated = LedgerPosition(symbol, shares, raw_price, traded_at)
        else:
            combined = previous.shares + shares
            average = (previous.average_cost * previous.shares + raw_price * shares) / combined
            updated = LedgerPosition(symbol, combined, average, min(previous.opened_at, traded_at))
        self.positions[symbol] = updated
        return PortfolioFill(symbol, Side.BUY, shares, raw_price, traded_at, fee)

    def sell(
        self,
        symbol: str,
        price: Decimal | int | float | str,
        requested_shares: int,
        traded_at: datetime,
    ) -> PortfolioFill:
        position = self.positions.get(symbol)
        shares = self._board_lot(requested_shares)
        if position is None or shares > position.shares:
            raise InsufficientPosition(f"not enough shares for {symbol}")
        if shares == 0:
            return PortfolioFill(symbol, Side.SELL, 0, as_decimal(price), traded_at, FeeBreakdown.zero())

        raw_price = as_decimal(price)
        fee = self.fees.calculate(side=Side.SELL, price=raw_price, shares=shares)
        gross = self.fees.quantize_money(raw_price * shares)
        self.cash = self.fees.quantize_money(self.cash + gross - fee.total)
        self.total_fees = self.fees.quantize_money(self.total_fees + fee.total)
        pnl = self.fees.quantize_money((raw_price - position.average_cost) * shares)
        self.realized_pnl = self.fees.quantize_money(self.realized_pnl + pnl)
        remaining = position.shares - shares
        if remaining:
            self.positions[symbol] = LedgerPosition(
                position.code,
                remaining,
                position.average_cost,
                position.opened_at,
            )
        else:
            self.positions.pop(symbol)
        return PortfolioFill(symbol, Side.SELL, shares, raw_price, traded_at, fee)

    def apply_fill(self, trade: MatchedTrade, requested_shares: int) -> PortfolioFill:
        if trade.side is Side.BUY:
            return self.buy(trade.code, trade.price, requested_shares, trade.traded_at)
        return self.sell(trade.code, trade.price, requested_shares, trade.traded_at)

    def snapshot(self, *, mark_prices: Mapping[str, Decimal | int | float | str]) -> PortfolioSnapshot:
        market_value = Decimal("0")
        unrealized = Decimal("0")
        for symbol, position in self.positions.items():
            if symbol not in mark_prices:
                raise ValueError(f"missing mark price for {symbol}")
            mark = as_decimal(mark_prices[symbol])
            market_value += mark * position.shares
            unrealized += (mark - position.average_cost) * position.shares
        market_value = self.fees.quantize_money(market_value)
        unrealized = self.fees.quantize_money(unrealized)
        equity = self.fees.quantize_money(self.cash + market_value)
        return PortfolioSnapshot(
            cash=self.cash,
            equity=equity,
            positions=MappingProxyType(dict(self.positions)),
            realized_pnl=self.realized_pnl,
            unrealized_pnl=unrealized,
            total_fees=self.total_fees,
        )

    def reconciles_to_cent(self, *, mark_prices: Mapping[str, Decimal | int | float | str]) -> bool:
        snapshot = self.snapshot(mark_prices=mark_prices)
        expected = self.fees.quantize_money(
            self.initial_cash + snapshot.realized_pnl + snapshot.unrealized_pnl - snapshot.total_fees
        )
        return abs(snapshot.equity - expected) <= Decimal("0.01")
