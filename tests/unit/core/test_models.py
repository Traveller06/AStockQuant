from dataclasses import FrozenInstanceError, fields
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from astock_quant.core.enums import DataHealth, Market, OrderStatus, RunStatus, Side
from astock_quant.core.models import Bar, Order, RunManifest, Signal, Trade


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_bar_rejects_naive_timestamp_and_invalid_ohlc():
    with pytest.raises(ValueError, match="timezone-aware"):
        Bar("600000", datetime(2026, 9, 12, 14, 55), 10, 11, 9, 10.5, 100, 1050, "fixture")
    with pytest.raises(ValueError, match="OHLC"):
        Bar(
            "600000",
            datetime(2026, 9, 12, 14, 55, tzinfo=SHANGHAI),
            10,
            9,
            11,
            10.5,
            100,
            1050,
            "fixture",
        )


def test_order_has_explicit_initial_state():
    order = Order.new("run-1", "paper", "600000", Market.SSE, Side.BUY, 100, 10.2)

    assert order.status is OrderStatus.NEW
    assert order.quantity == 100


def test_signal_factory_creates_stable_correlation_fields():
    timestamp = datetime(2026, 9, 25, 15, 0, tzinfo=SHANGHAI)
    first = Signal.new(
        source_run_id="run-1",
        strategy_id="weekly_trend_confirmation",
        code="600000",
        timestamp=timestamp,
        side=Side.BUY,
        strength=1.0,
        reason="突破回踩确认",
        parameter_version="weekly-trend-v1",
    )
    second = Signal.new(
        source_run_id="run-1",
        strategy_id="weekly_trend_confirmation",
        code="600000",
        timestamp=timestamp,
        side=Side.BUY,
        strength=1.0,
        reason="突破回踩确认",
        parameter_version="weekly-trend-v1",
    )

    assert first.signal_id
    assert first.signal_id == second.signal_id
    assert first.source_run_id == "run-1"


def test_order_can_retain_originating_signal_id():
    order = Order.new(
        "run-1", "paper", "600000", Market.SSE, Side.BUY, 100, 10.2, signal_id="sig-1"
    )
    assert order.signal_id == "sig-1"


@pytest.mark.parametrize(
    ("enum", "expected"),
    [
        (Market, {"SSE": "SSE", "SZSE": "SZSE", "BSE": "BSE"}),
        (Side, {"BUY": "buy", "SELL": "sell"}),
        (
            OrderStatus,
            {
                "NEW": "new",
                "SUBMITTED": "submitted",
                "PARTIALLY_FILLED": "partially_filled",
                "FILLED": "filled",
                "CANCELLED": "cancelled",
                "REJECTED": "rejected",
                "EXPIRED": "expired",
            },
        ),
        (
            RunStatus,
            {
                "NOT_STARTED": "not_started",
                "RUNNING": "running",
                "PAUSED": "paused",
                "FAILED": "failed",
                "INCOMPLETE": "incomplete",
                "COMPLETED": "completed",
            },
        ),
        (
            DataHealth,
            {
                "HEALTHY": "healthy",
                "DEGRADED": "degraded",
                "OFFLINE": "offline",
                "INCOMPLETE": "incomplete",
            },
        ),
    ],
)
def test_core_enums_have_stable_string_values(enum, expected):
    assert {member.name: member.value for member in enum} == expected


@pytest.mark.parametrize(
    ("open_price", "high", "low", "close", "volume", "amount", "message"),
    [
        (0, 11, 9, 10.5, 100, 1050, "OHLC"),
        (10, 11, 9, float("nan"), 100, 1050, "OHLC"),
        (10, 11, 9, 10.5, -1, 1050, "volume"),
        (10, 11, 9, 10.5, float("nan"), 1050, "volume"),
        (10, 11, 9, 10.5, 100, -1, "amount"),
        (10, 11, 9, 10.5, 100, float("nan"), "amount"),
    ],
)
def test_bar_rejects_invalid_prices_and_nonnegative_market_data(
    open_price, high, low, close, volume, amount, message
):
    with pytest.raises(ValueError, match=message):
        Bar(
            "600000",
            datetime(2026, 9, 12, 14, 55, tzinfo=SHANGHAI),
            open_price,
            high,
            low,
            close,
            volume,
            amount,
            "fixture",
        )


def test_bar_is_frozen_after_validation():
    bar = Bar("600000", datetime(2026, 9, 12, 14, 55, tzinfo=SHANGHAI), 10, 11, 9, 10.5, 100, 1050, "fixture")

    with pytest.raises(FrozenInstanceError):
        bar.close = 11


@pytest.mark.parametrize(
    ("quantity", "limit_price", "message"),
    [
        (0, 10.2, "quantity"),
        (100, 0, "limit_price"),
        (100, float("nan"), "limit_price"),
        (99, 10.2, "100"),
    ],
)
def test_order_new_rejects_invalid_a_share_limit_orders(quantity, limit_price, message):
    with pytest.raises(ValueError, match=message):
        Order.new("run-1", "paper", "600000", Market.SSE, Side.BUY, quantity, limit_price)


def test_order_and_trade_have_stable_field_contracts():
    assert [field.name for field in fields(Order)] == [
        "order_id",
        "source_run_id",
        "broker_id",
        "code",
        "market",
        "side",
        "quantity",
        "limit_price",
        "status",
        "created_at",
        "filled_quantity",
        "signal_id",
    ]
    assert [field.name for field in fields(Trade)] == [
        "trade_id",
        "order_id",
        "source_run_id",
        "broker_id",
        "code",
        "side",
        "quantity",
        "price",
        "commission",
        "stamp_tax",
        "slippage",
        "traded_at",
        "signal_id",
    ]


def test_run_manifest_has_exact_persisted_contract():
    assert [field.name for field in fields(RunManifest)] == [
        "run_id",
        "app_version",
        "strategy_id",
        "strategy_version",
        "parameters",
        "sample_sha256",
        "data_cutoff",
        "data_sha256",
        "status",
        "started_at",
        "finished_at",
        "errors",
    ]
