"""Stable enumerations shared by the trading domain."""

from enum import Enum


class Market(str, Enum):
    SSE = "SSE"
    SZSE = "SZSE"
    BSE = "BSE"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    NEW = "new"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class RunStatus(str, Enum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    COMPLETED = "completed"


class DataHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    INCOMPLETE = "incomplete"
