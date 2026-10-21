"""Detection and priority selection of weekly entry setups."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from astock_quant.indicators.moving_average import moving_average
from astock_quant.indicators.swing_detector import SwingKind, SwingPoint
from astock_quant.indicators.weekly_bars import WeeklyBar

from .config import WeeklyTrendConfig
from .models import RuleCheck, SetupAssessment, SetupHit, SetupKind, TrendAssessment


def _check(code: str, passed: bool, actual: str, threshold: str, reason_zh: str) -> RuleCheck:
    return RuleCheck(code, passed, actual, threshold, reason_zh)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def detect_setups(
    weeks: Sequence[WeeklyBar],
    swings: Sequence[SwingPoint],
    trend: TrendAssessment,
    config: WeeklyTrendConfig,
    *,
    prior_breakout_price: float | None = None,
    as_of: datetime | None = None,
) -> SetupAssessment:
    """Return all setup hits and one deterministic priority-selected hit."""

    if as_of is None:
        if not weeks:
            raise ValueError("as_of is required when weeks are empty")
        as_of = weeks[-1].end
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    visible = tuple(week for week in weeks if week.end <= as_of)

    if not trend.qualified or not trend.sufficient_data:
        gate = _check(
            "setup.trend_gate",
            False,
            f"qualified={trend.qualified}, sufficient_data={trend.sufficient_data}",
            "周线趋势合格且数据充足",
            "周线趋势门槛未通过，不建立形态",
        )
        return SetupAssessment((), None, (gate,), as_of)
    if not visible:
        history = _check("setup.history", False, "0", "至少1个完整周", "没有可见完整周")
        return SetupAssessment((), None, (history,), as_of)

    current = visible[-1]
    checks: list[RuleCheck] = []
    hits: list[SetupHit] = []
    lookback = config.volume_lookback
    prior_volumes = tuple(week.volume for week in visible[-lookback - 1 : -1])
    prior_volume_mean = _mean(prior_volumes) if len(prior_volumes) == lookback else None

    confirmed_highs = sorted(
        (
            point
            for point in swings
            if point.kind is SwingKind.HIGH and point.confirmed_at <= as_of
        ),
        key=lambda point: (point.confirmed_at, point.pivot_at),
    )
    previous_high = confirmed_highs[-1] if confirmed_highs else None
    breakout_close_ok = previous_high is not None and current.close > previous_high.price
    breakout_volume_ok = (
        prior_volume_mean is not None
        and current.volume >= prior_volume_mean * float(config.breakout_volume_multiple)
    )
    breakout_checks = (
        _check(
            "setup.breakout.close",
            breakout_close_ok,
            f"{current.close:.6g}" if previous_high else "无已确认前高",
            f"> {previous_high.price:.6g}" if previous_high else "需要已确认前高",
            "周收盘价突破已确认前高" if breakout_close_ok else "周收盘价未严格突破已确认前高",
        ),
        _check(
            "setup.breakout.volume",
            breakout_volume_ok,
            f"{current.volume:.6g}",
            (
                f">= {prior_volume_mean * float(config.breakout_volume_multiple):.6g}"
                if prior_volume_mean is not None
                else f"需要此前{lookback}个完整周"
            ),
            "突破周量能达到最低要求" if breakout_volume_ok else "突破周量能不足或历史不足",
        ),
    )
    checks.extend(breakout_checks)
    if breakout_close_ok and breakout_volume_ok and previous_high is not None:
        hits.append(
            SetupHit(
                SetupKind.BREAKOUT,
                current.end,
                previous_high.price,
                "已确认摆动前高",
                breakout_checks,
            )
        )

    closes = tuple(week.close for week in visible)
    short, medium, long = config.weekly_ma_periods
    short_ma = moving_average(closes, short)
    medium_ma = moving_average(closes, medium)
    cross_ok = (
        len(visible) >= medium + 1
        and short_ma[-2] is not None
        and medium_ma[-2] is not None
        and short_ma[-1] is not None
        and medium_ma[-1] is not None
        and short_ma[-2] <= medium_ma[-2]
        and short_ma[-1] > medium_ma[-1]
    )
    above_previous_volume = len(visible) >= 2 and current.volume > visible[-2].volume
    golden_mean_volume = prior_volume_mean is not None and current.volume >= prior_volume_mean
    golden_checks = (
        _check(
            "setup.golden_cross.cross",
            cross_ok,
            (
                f"MA{short}W={short_ma[-1]:.6g}, MA{medium}W={medium_ma[-1]:.6g}"
                if short_ma[-1] is not None and medium_ma[-1] is not None
                else "均线历史不足"
            ),
            f"MA{short}W由不高于MA{medium}W变为高于",
            "短周均线上穿中周均线" if cross_ok else "未形成有效周均线金叉",
        ),
        _check(
            "setup.golden_cross.above_previous_volume",
            above_previous_volume,
            f"{current.volume:.6g}",
            f"> {visible[-2].volume:.6g}" if len(visible) >= 2 else "需要前一完整周",
            "当前周成交量高于前一周" if above_previous_volume else "当前周成交量未高于前一周",
        ),
        _check(
            "setup.golden_cross.prior_mean_volume",
            golden_mean_volume,
            f"{current.volume:.6g}",
            f">= {prior_volume_mean:.6g}" if prior_volume_mean is not None else f"需要此前{lookback}个完整周",
            "当前周成交量不低于此前均量" if golden_mean_volume else "当前周成交量低于此前均量或历史不足",
        ),
    )
    checks.extend(golden_checks)
    if all(check.passed for check in golden_checks):
        hits.append(
            SetupHit(
                SetupKind.GOLDEN_CROSS,
                current.end,
                current.close,
                f"MA{short}W上穿MA{medium}W",
                golden_checks,
            )
        )

    averages = {
        period: moving_average(closes, period)[-1]
        for period in (short, medium, long)
    }
    supports: list[tuple[str, float]] = [
        (f"MA{period}W", value)
        for period, value in averages.items()
        if value is not None
    ]
    if prior_breakout_price is not None:
        if prior_breakout_price <= 0:
            raise ValueError("prior_breakout_price must be positive")
        supports.append(("最近有效突破位", prior_breakout_price))

    tolerance = float(config.support_tolerance)
    for label, support in supports:
        intersects = current.low <= support * (1 + tolerance) and current.high >= support * (1 - tolerance)
        reclaimed = current.close > support
        support_checks = (
            _check(
                f"setup.pullback.{label}.zone",
                intersects,
                f"[{current.low:.6g}, {current.high:.6g}]",
                f"与[{support * (1 - tolerance):.6g}, {support * (1 + tolerance):.6g}]相交",
                f"周价格区间触及{label}支撑区" if intersects else f"周价格区间未触及{label}支撑区",
            ),
            _check(
                f"setup.pullback.{label}.reclaim",
                reclaimed,
                f"{current.close:.6g}",
                f"> {support:.6g}",
                f"周收盘重新站上{label}" if reclaimed else f"周收盘未严格站上{label}",
            ),
        )
        checks.extend(support_checks)
        if intersects and reclaimed:
            hits.append(SetupHit(SetupKind.PULLBACK, current.end, support, label, support_checks))

    selected: SetupHit | None = None
    for kind in SetupKind.priority():
        matching = [hit for hit in hits if hit.kind is kind]
        if matching:
            selected = max(matching, key=lambda hit: hit.reference_price)
            break
    return SetupAssessment(tuple(hits), selected, tuple(checks), as_of)
