"""Causal evaluation of the weekly uptrend gate."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from astock_quant.indicators.moving_average import moving_average
from astock_quant.indicators.swing_detector import SwingKind, SwingPoint
from astock_quant.indicators.weekly_bars import WeeklyBar

from .config import WeeklyTrendConfig
from .models import RuleCheck, TrendAssessment


def _check(code: str, passed: bool, actual: str, threshold: str, reason_zh: str) -> RuleCheck:
    return RuleCheck(code, passed, actual, threshold, reason_zh)


def assess_weekly_trend(
    weeks: Sequence[WeeklyBar],
    swings: Sequence[SwingPoint],
    config: WeeklyTrendConfig,
    *,
    as_of: datetime | None = None,
) -> TrendAssessment:
    """Evaluate all hard trend rules using only information visible at ``as_of``."""

    if as_of is None:
        if not weeks:
            raise ValueError("as_of is required when weeks are empty")
        as_of = weeks[-1].end
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    visible_weeks = tuple(week for week in weeks if week.end <= as_of)
    periods = config.weekly_ma_periods
    required_weeks = max(periods) + 1
    if len(visible_weeks) < required_weeks:
        history = _check(
            "trend.ma_history",
            False,
            str(len(visible_weeks)),
            str(required_weeks),
            f"完整周线仅有{len(visible_weeks)}周，至少需要{required_weeks}周",
        )
        return TrendAssessment(False, False, (history,), as_of)

    visible_swings = sorted(
        (point for point in swings if point.confirmed_at <= as_of),
        key=lambda point: (point.confirmed_at, point.pivot_at, point.kind.value),
    )
    highs = [point for point in visible_swings if point.kind is SwingKind.HIGH]
    lows = [point for point in visible_swings if point.kind is SwingKind.LOW]
    if len(highs) < 2 or len(lows) < 2:
        history = _check(
            "trend.swing_history",
            False,
            f"高点{len(highs)}个/低点{len(lows)}个",
            "已确认高点和低点各至少2个",
            "已确认摆动高低点历史不足",
        )
        return TrendAssessment(False, False, (history,), as_of)

    closes = tuple(week.close for week in visible_weeks)
    averages = {period: moving_average(closes, period) for period in periods}
    current = {period: averages[period][-1] for period in periods}
    previous = {period: averages[period][-2] for period in periods}
    if any(value is None for value in (*current.values(), *previous.values())):
        raise RuntimeError("validated moving-average history produced unavailable values")

    short, medium, long = periods
    ma_order_ok = current[short] > current[medium] > current[long]  # type: ignore[operator]
    ma_rising_ok = all(current[period] > previous[period] for period in periods)  # type: ignore[operator]
    two_closes_ok = (
        closes[-2] >= averages[long][-2]  # type: ignore[operator]
        and closes[-1] >= averages[long][-1]  # type: ignore[operator]
    )
    higher_highs_ok = highs[-1].price > highs[-2].price
    higher_lows_ok = lows[-1].price > lows[-2].price

    checks = (
        _check(
            "trend.ma_order",
            ma_order_ok,
            f"{current[short]:.6g}>{current[medium]:.6g}>{current[long]:.6g}",
            f"MA{short}W > MA{medium}W > MA{long}W",
            "周均线多头排列成立" if ma_order_ok else "周均线多头排列不成立",
        ),
        _check(
            "trend.ma_rising",
            ma_rising_ok,
            ", ".join(f"MA{period}W:{previous[period]:.6g}->{current[period]:.6g}" for period in periods),
            "三条周均线当前值均严格高于上一完整周",
            "三条周均线均向上" if ma_rising_ok else "至少一条周均线没有向上",
        ),
        _check(
            "trend.two_closes_above_ma20",
            two_closes_ok,
            f"{closes[-2]:.6g}/{averages[long][-2]:.6g}, {closes[-1]:.6g}/{averages[long][-1]:.6g}",
            f"最近两周收盘价均不低于MA{long}W",
            "最近两周收盘价守住长期周均线" if two_closes_ok else "最近两周至少一次跌破长期周均线",
        ),
        _check(
            "trend.higher_highs",
            higher_highs_ok,
            f"{highs[-2].price:.6g}->{highs[-1].price:.6g}",
            "后一个已确认摆动高点严格高于前一个",
            "已确认摆动高点抬高" if higher_highs_ok else "已确认摆动高点未抬高",
        ),
        _check(
            "trend.higher_lows",
            higher_lows_ok,
            f"{lows[-2].price:.6g}->{lows[-1].price:.6g}",
            "后一个已确认摆动低点严格高于前一个",
            "已确认摆动低点抬高" if higher_lows_ok else "已确认摆动低点未抬高",
        ),
    )
    return TrendAssessment(all(check.passed for check in checks), True, checks, as_of)
