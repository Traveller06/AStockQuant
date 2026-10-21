"""Explicit A-share commission, stamp-tax, and slippage calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from astock_quant.core.enums import Side

from .models import as_decimal


CENT = Decimal("0.01")


@dataclass(frozen=True)
class FeeBreakdown:
    commission: Decimal
    stamp_tax: Decimal
    slippage: Decimal

    @property
    def total(self) -> Decimal:
        return self.commission + self.stamp_tax + self.slippage

    @classmethod
    def zero(cls) -> FeeBreakdown:
        return cls(Decimal("0.00"), Decimal("0.00"), Decimal("0.00"))


@dataclass(frozen=True)
class FeeSchedule:
    commission_rate: Decimal
    minimum_commission: Decimal
    stamp_tax_rate: Decimal
    slippage_rate: Decimal

    @classmethod
    def default(cls) -> FeeSchedule:
        return cls(
            commission_rate=Decimal("0.0003"),
            minimum_commission=Decimal("5"),
            stamp_tax_rate=Decimal("0.0005"),
            slippage_rate=Decimal("0.001"),
        )

    @staticmethod
    def quantize_money(value: Decimal | int | float | str) -> Decimal:
        return as_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)

    def calculate(
        self,
        *,
        side: Side | str,
        price: Decimal | int | float | str,
        shares: int,
    ) -> FeeBreakdown:
        if shares < 0:
            raise ValueError("shares must not be negative")
        if shares == 0:
            return FeeBreakdown.zero()
        normalized_side = side if isinstance(side, Side) else Side(side)
        gross = as_decimal(price) * shares
        if gross <= 0:
            raise ValueError("trade value must be positive")
        commission = max(self.minimum_commission, gross * self.commission_rate)
        stamp_tax = gross * self.stamp_tax_rate if normalized_side is Side.SELL else Decimal("0")
        slippage = gross * self.slippage_rate
        return FeeBreakdown(
            commission=self.quantize_money(commission),
            stamp_tax=self.quantize_money(stamp_tax),
            slippage=self.quantize_money(slippage),
        )
