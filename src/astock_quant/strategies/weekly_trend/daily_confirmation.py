"""Causal daily confirmation for an active weekly setup."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from astock_quant.core.models import Bar
from astock_quant.indicators.moving_average import moving_average

from .config import WeeklyTrendConfig
from .models import ConfirmationResult, PatternState, PatternStatus, RuleCheck, SetupKind


def _check(code: str, passed: bool, actual: str, threshold: str, reason_zh: str) -> RuleCheck:
    return RuleCheck(code, passed, actual, threshold, reason_zh)


def _format(value: float) -> str:
    return f"{value:.12g}"


def confirm_daily_setup(
    state: PatternState,
    daily_bars: Sequence[Bar],
    config: WeeklyTrendConfig,
    *,
    as_of: datetime | None = None,
) -> ConfirmationResult:
    """Confirm one waiting setup using only daily bars visible at ``as_of``."""

    if state.status is not PatternStatus.WAITING_CONFIRMATION:
        raise ValueError("daily confirmation requires a waiting state")
    if state.setup is None:
        raise ValueError("waiting state requires a setup")
    if as_of is None:
        if not daily_bars:
            raise ValueError("as_of is required when daily_bars are empty")
        as_of = daily_bars[-1].timestamp
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    visible = tuple(bar for bar in daily_bars if bar.timestamp <= as_of)
    if any(left.timestamp >= right.timestamp for left, right in zip(visible, visible[1:])):
        raise ValueError("daily bars must be strictly increasing")
    if any(bar.code != state.code for bar in visible):
        raise ValueError("daily bar code must match pattern state")
    if not visible:
        return ConfirmationResult(False, (), as_of, "confirm.insufficient_data", "没有可用日线数据")

    current = visible[-1]
    if current.timestamp.date() > state.expires_on:
        return ConfirmationResult(False, (), as_of, "confirm.expired", "形态已超过有效期")

    required_prior = max(config.stabilization_lookback, config.volume_lookback)
    if len(visible) < required_prior + 1:
        check = _check(
            "confirm.history",
            False,
            str(len(visible) - 1),
            f">= {required_prior}",
            "日线历史不足，不能确认形态",
        )
        return ConfirmationResult(False, (check,), as_of, "confirm.insufficient_data", "日线历史不足")

    prior_lows = tuple(bar.low for bar in visible[-config.stabilization_lookback - 1 : -1])
    low_floor = min(prior_lows) * (1 - float(config.stabilization_low_tolerance))
    low_ok = current.low >= low_floor
    close_up = current.close > visible[-2].close
    bullish = current.close > current.open
    prior_volumes = tuple(bar.volume for bar in visible[-config.volume_lookback - 1 : -1])
    volume_threshold = (sum(prior_volumes) / len(prior_volumes)) * float(config.daily_volume_multiple)
    volume_ok = current.volume >= volume_threshold

    checks: list[RuleCheck] = [
        _check(
            "confirm.stabilization.low",
            low_ok,
            _format(current.low),
            f">= {_format(low_floor)}",
            "当前低点守住三日低点容差" if low_ok else "当前低点跌破三日低点容差",
        ),
        _check(
            "confirm.stabilization.close_up",
            close_up,
            _format(current.close),
            f"> {_format(visible[-2].close)}",
            "当前收盘高于前一日" if close_up else "当前收盘未高于前一日",
        ),
        _check(
            "confirm.stabilization.bullish",
            bullish,
            _format(current.close),
            f"> {_format(current.open)}",
            "当前日线收阳" if bullish else "当前日线未收阳",
        ),
        _check(
            "confirm.volume",
            volume_ok,
            _format(current.volume),
            f">= {_format(volume_threshold)}",
            "日成交量达到确认门槛" if volume_ok else "日成交量未达到确认门槛",
        ),
    ]

    if state.setup.kind is SetupKind.BREAKOUT:
        reference = state.setup.reference_price
        tolerance = float(config.support_tolerance)
        zone_ok = current.low <= reference * (1 + tolerance) and current.high >= reference * (1 - tolerance)
        reclaim_ok = current.close > reference
        checks.extend(
            (
                _check(
                    "confirm.breakout_zone",
                    zone_ok,
                    f"[{_format(current.low)}, {_format(current.high)}]",
                    f"与[{_format(reference * (1 - tolerance))}, {_format(reference * (1 + tolerance))}]相交",
                    "当日价格触及突破位容差区" if zone_ok else "当日价格未触及突破位容差区",
                ),
                _check(
                    "confirm.breakout_reclaim",
                    reclaim_ok,
                    _format(current.close),
                    f"> {_format(reference)}",
                    "收盘重新站上突破位" if reclaim_ok else "收盘未严格站上突破位",
                ),
            )
        )
    else:
        ma_values = moving_average(tuple(bar.close for bar in visible), config.daily_ma_period)
        ma10 = ma_values[-1]
        ma_ok = ma10 is not None and current.close > ma10
        checks.append(
            _check(
                "confirm.ma10_reclaim",
                ma_ok,
                _format(current.close),
                f"> {_format(ma10)}" if ma10 is not None else f"需要{config.daily_ma_period}日均线历史",
                "收盘严格站上日均线" if ma_ok else "收盘未严格站上日均线或历史不足",
            )
        )

    confirmed = all(check.passed for check in checks)
    return ConfirmationResult(
        confirmed,
        tuple(checks),
        as_of,
        "confirm.ok" if confirmed else "confirm.rejected",
        "日线确认通过" if confirmed else "日线确认条件未全部通过",
    )
