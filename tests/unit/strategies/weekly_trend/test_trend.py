from dataclasses import replace
from datetime import timedelta

import pytest

from astock_quant.indicators.swing_detector import SwingKind, SwingPoint
from astock_quant.strategies.weekly_trend.config import WeeklyTrendConfig
from astock_quant.strategies.weekly_trend.trend import assess_weekly_trend
from tests.fixtures.weekly_trend import rising_swings, rising_weeks


@pytest.fixture
def uptrend_fixture():
    weeks = rising_weeks()
    return weeks, rising_swings(weeks), WeeklyTrendConfig()


def test_trend_requires_ma_order_rising_mas_two_closes_and_higher_swings(uptrend_fixture) -> None:
    result = assess_weekly_trend(*uptrend_fixture)

    assert result.qualified is True
    assert result.sufficient_data is True
    assert {check.code for check in result.checks} == {
        "trend.ma_order",
        "trend.ma_rising",
        "trend.two_closes_above_ma20",
        "trend.higher_highs",
        "trend.higher_lows",
    }
    assert all(check.reason_zh for check in result.checks)


def test_missing_two_confirmed_highs_or_lows_is_insufficient(uptrend_fixture) -> None:
    weeks, swings, config = uptrend_fixture
    result = assess_weekly_trend(weeks, swings[:2], config)

    assert result.qualified is False
    assert result.sufficient_data is False
    assert any(check.code == "trend.swing_history" for check in result.checks)


@pytest.mark.parametrize(
    ("mutation", "failed_code"),
    (
        ("ma_order", "trend.ma_order"),
        ("ma5_flat", "trend.ma_rising"),
        ("close_below_ma20", "trend.two_closes_above_ma20"),
        ("lower_high", "trend.higher_highs"),
        ("lower_low", "trend.higher_lows"),
    ),
)
def test_each_hard_condition_blocks_trend(uptrend_fixture, mutation: str, failed_code: str) -> None:
    weeks, swings, config = uptrend_fixture
    weeks = list(weeks)
    swings = list(swings)
    if mutation == "ma_order":
        weeks[-1] = replace(weeks[-1], close=5.0)
    elif mutation == "ma5_flat":
        weeks[-1] = replace(weeks[-1], close=weeks[-6].close)
    elif mutation == "close_below_ma20":
        weeks[-2] = replace(weeks[-2], close=1.0)
        weeks[-1] = replace(weeks[-1], close=1.0)
    elif mutation == "lower_high":
        swings[2] = replace(swings[2], price=12.5)
    elif mutation == "lower_low":
        swings[3] = replace(swings[3], price=11.5)

    result = assess_weekly_trend(tuple(weeks), tuple(swings), config)

    assert result.qualified is False
    assert next(check for check in result.checks if check.code == failed_code).passed is False


def test_missing_ma_history_is_insufficient() -> None:
    weeks = rising_weeks(20)
    result = assess_weekly_trend(weeks, rising_swings(rising_weeks()), WeeklyTrendConfig())

    assert result.sufficient_data is False
    assert result.qualified is False
    assert result.checks[0].code == "trend.ma_history"


def test_appending_future_data_preserves_assessment_at_original_cutoff(uptrend_fixture) -> None:
    weeks, swings, config = uptrend_fixture
    cutoff = weeks[-1].end
    next_end = cutoff + timedelta(days=7)
    future_week = replace(
        weeks[-1],
        start=next_end - timedelta(days=4),
        end=next_end,
        close=2.0,
    )
    future_swing = SwingPoint(SwingKind.HIGH, next_end, next_end, 1.0)

    prefix = assess_weekly_trend(weeks, swings, config, as_of=cutoff)
    extended = assess_weekly_trend(weeks + (future_week,), swings + (future_swing,), config, as_of=cutoff)

    assert extended == prefix
