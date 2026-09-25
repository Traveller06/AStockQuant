from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from astock_quant.backtest.fees import FeeSchedule
from astock_quant.backtest.portfolio import InsufficientPosition, PortfolioLedger


SHANGHAI_OPEN = datetime(2026, 9, 11, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
NEXT_OPEN = datetime(2026, 9, 14, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_fee_schedule_applies_minimum_commission_and_sell_stamp_tax() -> None:
    fees = FeeSchedule.default()

    buy = fees.calculate(side="buy", price=Decimal("10"), shares=100)
    sell = fees.calculate(side="sell", price=Decimal("10"), shares=100)

    assert buy.commission == Decimal("5.00")
    assert buy.stamp_tax == Decimal("0.00")
    assert buy.slippage == Decimal("1.00")
    assert sell.commission == Decimal("5.00")
    assert sell.stamp_tax == Decimal("0.50")
    assert sell.slippage == Decimal("1.00")


def test_ledger_uses_board_lots_and_never_overdraws() -> None:
    ledger = PortfolioLedger(initial_cash=Decimal("100000"), fees=FeeSchedule.default())

    fill = ledger.buy(
        symbol="600000",
        price=Decimal("10.01"),
        requested_shares=999,
        traded_at=SHANGHAI_OPEN,
    )

    assert fill.shares == 900
    assert fill.shares % 100 == 0
    assert ledger.cash >= 0
    assert ledger.reconciles_to_cent(mark_prices={"600000": Decimal("10.01")})


def test_ledger_reduces_order_to_affordable_board_lot() -> None:
    ledger = PortfolioLedger(initial_cash=Decimal("1005"), fees=FeeSchedule.default())

    fill = ledger.buy(
        symbol="600000",
        price=Decimal("10"),
        requested_shares=200,
        traded_at=SHANGHAI_OPEN,
    )

    assert fill.shares == 0
    assert ledger.cash == Decimal("1005.00")
    assert not ledger.positions


def test_buy_then_sell_reconciles_cash_realized_pnl_and_fees() -> None:
    ledger = PortfolioLedger(initial_cash=Decimal("100000"), fees=FeeSchedule.default())
    buy = ledger.buy("600000", Decimal("10"), 1000, SHANGHAI_OPEN)
    sell = ledger.sell("600000", Decimal("11"), 1000, NEXT_OPEN)

    snapshot = ledger.snapshot(mark_prices={})

    assert buy.shares == sell.shares == 1000
    assert snapshot.positions == {}
    assert snapshot.realized_pnl == Decimal("1000.00")
    assert snapshot.total_fees == buy.fees.total + sell.fees.total
    assert snapshot.equity == ledger.initial_cash + snapshot.realized_pnl - snapshot.total_fees
    assert ledger.reconciles_to_cent(mark_prices={})


def test_snapshot_reconciles_unrealized_position_to_cent() -> None:
    ledger = PortfolioLedger(initial_cash=Decimal("100000"), fees=FeeSchedule.default())
    ledger.buy("600000", Decimal("10"), 1000, SHANGHAI_OPEN)

    snapshot = ledger.snapshot(mark_prices={"600000": Decimal("10.50")})

    assert snapshot.unrealized_pnl == Decimal("500.00")
    assert snapshot.equity == (
        ledger.initial_cash + snapshot.realized_pnl + snapshot.unrealized_pnl - snapshot.total_fees
    )
    assert ledger.reconciles_to_cent(mark_prices={"600000": Decimal("10.50")})


def test_sell_rejects_more_than_the_owned_position() -> None:
    ledger = PortfolioLedger(initial_cash=Decimal("100000"), fees=FeeSchedule.default())
    ledger.buy("600000", Decimal("10"), 100, SHANGHAI_OPEN)

    with pytest.raises(InsufficientPosition):
        ledger.sell("600000", Decimal("11"), 200, NEXT_OPEN)
