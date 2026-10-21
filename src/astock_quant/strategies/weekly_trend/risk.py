"""Initial-stop selection and weekly trend exit decisions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from astock_quant.indicators.swing_detector import SwingKind, SwingPoint

from .models import RuleCheck


@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    reason_code: str
    reason_zh: str
    as_of: datetime
    checks: tuple[RuleCheck, ...]

    def __post_init__(self) -> None:
        if not self.reason_code.strip() or not self.reason_zh.strip():
            raise ValueError("exit decision reasons must not be empty")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")


def initial_stop(swings: Sequence[SwingPoint], signal_time: datetime) -> float | None:
    """Return the latest swing low that was confirmed by signal close."""

    if signal_time.tzinfo is None or signal_time.utcoffset() is None:
        raise ValueError("signal_time must be timezone-aware")
    visible = sorted(
        (
            point
            for point in swings
            if point.kind is SwingKind.LOW and point.confirmed_at <= signal_time
        ),
        key=lambda point: (point.confirmed_at, point.pivot_at),
    )
    return visible[-1].price if visible else None


def trend_exit(
    *,
    weekly_close: float,
    ma20: float,
    ma_order_intact: bool,
    swing_structure_intact: bool,
    as_of: datetime,
) -> ExitDecision:
    """Evaluate the three hard weekly exit conditions in stable priority order."""

    if not isfinite(weekly_close) or weekly_close <= 0 or not isfinite(ma20) or ma20 <= 0:
        raise ValueError("weekly_close and ma20 must be finite positive prices")
    close_safe = weekly_close >= ma20
    checks = (
        RuleCheck(
            "exit.close_above_ma20",
            close_safe,
            f"{weekly_close:.12g}",
            f">= {ma20:.12g}",
            "周收盘未跌破MA20W" if close_safe else "周收盘跌破MA20W",
        ),
        RuleCheck(
            "exit.ma_order_intact",
            ma_order_intact,
            str(ma_order_intact).lower(),
            "true",
            "周均线多头排列保持" if ma_order_intact else "周均线多头排列被破坏",
        ),
        RuleCheck(
            "exit.swing_structure_intact",
            swing_structure_intact,
            str(swing_structure_intact).lower(),
            "true",
            "摆动高低点结构保持" if swing_structure_intact else "摆动高低点结构被破坏",
        ),
    )
    if not close_safe:
        reason_code, reason_zh = "exit.close_below_ma20", "周收盘跌破MA20W，生成退出意图"
    elif not ma_order_intact:
        reason_code, reason_zh = "exit.ma_order_broken", "周均线多头排列破坏，生成退出意图"
    elif not swing_structure_intact:
        reason_code, reason_zh = "exit.swing_structure_broken", "周线摆动结构破坏，生成退出意图"
    else:
        reason_code, reason_zh = "exit.hold", "周线趋势保持，继续持有"
    return ExitDecision(reason_code != "exit.hold", reason_code, reason_zh, as_of, checks)
