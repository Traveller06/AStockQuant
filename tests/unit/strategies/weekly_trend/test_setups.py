from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from astock_quant.indicators.swing_detector import SwingKind, SwingPoint
from astock_quant.indicators.weekly_bars import WeeklyBar
from astock_quant.strategies.weekly_trend.config import WeeklyTrendConfig
from astock_quant.strategies.weekly_trend.models import RuleCheck, SetupKind, TrendAssessment
from astock_quant.strategies.weekly_trend.setups import detect_setups


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _weeks(
    closes: tuple[float, ...],
    *,
    current_volume: float = 150.0,
    current_low: float | None = None,
    current_high: float | None = None,
) -> tuple[WeeklyBar, ...]:
    first_end = datetime(2026, 1, 9, 15, 0, tzinfo=SHANGHAI)
    result = []
    for index, close in enumerate(closes):
        end = first_end + timedelta(days=7 * index)
        low = close - 0.3
        high = close + 0.3
        if index == len(closes) - 1:
            low = current_low if current_low is not None else low
            high = current_high if current_high is not None else high
        volume = current_volume if index == len(closes) - 1 else 100.0
        result.append(
            WeeklyBar(
                code="600000",
                start=end - timedelta(days=4),
                end=end,
                open=(low + high) / 2,
                high=high,
                low=low,
                close=close,
                volume=volume,
                amount=volume * close,
                source="fixture",
            )
        )
    return tuple(result)


def _trend(weeks: tuple[WeeklyBar, ...]) -> TrendAssessment:
    check = RuleCheck("trend.fixture", True, "通过", "通过", "周线趋势通过")
    return TrendAssessment(True, True, (check,), weeks[-1].end)


def _previous_high(weeks: tuple[WeeklyBar, ...], price: float = 12.0) -> SwingPoint:
    return SwingPoint(SwingKind.HIGH, weeks[-4].end, weeks[-3].end, price)


def test_breakout_requires_strict_close_above_high_and_inclusive_volume_boundary() -> None:
    weeks = _weeks((10.0, 10.2, 10.4, 10.6, 10.8, 11.0, 12.1), current_volume=150.0)
    config = WeeklyTrendConfig(breakout_volume_multiple=Decimal("1.5"))

    result = detect_setups(weeks, (_previous_high(weeks),), _trend(weeks), config)

    assert result.selected is not None
    assert result.selected.kind is SetupKind.BREAKOUT
    assert result.selected.reference_price == 12.0

    equal_close = replace(weeks[-1], close=12.0)
    rejected = detect_setups(weeks[:-1] + (equal_close,), (_previous_high(weeks),), _trend(weeks), config)
    assert not any(hit.kind is SetupKind.BREAKOUT for hit in rejected.hits)


def test_golden_cross_requires_both_weekly_volume_checks() -> None:
    weeks = _weeks((10.0,) * 20 + (12.0,), current_volume=100.0)

    accepted = detect_setups(weeks, (), _trend(weeks), WeeklyTrendConfig())
    assert accepted.selected is None  # volume is not above the prior week

    series = _weeks((10.0,) * 20 + (12.0,), current_volume=101.0)
    accepted = detect_setups(series, (), _trend(series), WeeklyTrendConfig())
    assert accepted.selected is not None and accepted.selected.kind is SetupKind.GOLDEN_CROSS

    below_average = _weeks((10.0,) * 20 + (12.0,), current_volume=99.0)
    assert detect_setups(below_average, (), _trend(below_average), WeeklyTrendConfig()).selected is None


def test_pullback_keeps_all_support_hits_and_selects_highest() -> None:
    weeks = _weeks((10.0,) * 20 + (10.2,), current_volume=100.0, current_low=9.7, current_high=10.3)

    result = detect_setups(
        weeks,
        (_previous_high(weeks, 20.0),),
        _trend(weeks),
        WeeklyTrendConfig(),
        prior_breakout_price=10.1,
    )

    pullbacks = [hit for hit in result.hits if hit.kind is SetupKind.PULLBACK]
    assert len(pullbacks) == 4
    assert result.selected is not None
    assert result.selected.kind is SetupKind.PULLBACK
    assert result.selected.reference_price == 10.1


def test_same_week_records_all_kinds_but_selects_breakout() -> None:
    weeks = _weeks((10.0,) * 20 + (13.0,), current_volume=150.0, current_low=9.5, current_high=13.5)

    result = detect_setups(
        weeks,
        (_previous_high(weeks, 12.0),),
        _trend(weeks),
        WeeklyTrendConfig(),
        prior_breakout_price=10.2,
    )

    assert {hit.kind for hit in result.hits} == {
        SetupKind.BREAKOUT,
        SetupKind.GOLDEN_CROSS,
        SetupKind.PULLBACK,
    }
    assert result.selected is not None and result.selected.kind is SetupKind.BREAKOUT
    assert {check.code.split(".")[1] for check in result.checks} >= {
        "breakout",
        "golden_cross",
        "pullback",
    }


def test_unqualified_trend_blocks_every_setup() -> None:
    weeks = _weeks((10.0,) * 20 + (13.0,), current_volume=150.0)
    trend = replace(_trend(weeks), qualified=False)

    result = detect_setups(weeks, (_previous_high(weeks),), trend, WeeklyTrendConfig())

    assert result.hits == ()
    assert result.selected is None
    assert result.checks[0].code == "setup.trend_gate"
