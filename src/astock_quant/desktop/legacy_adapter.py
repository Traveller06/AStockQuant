"""Read-only conversion of the historical v7 pandas cache into v8 contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Mapping

import pandas as pd

from astock_quant.backtest.models import ExecutionBar
from astock_quant.core.models import Bar
from astock_quant.data.calendar import SHANGHAI, TradingCalendar


@dataclass(frozen=True)
class LegacyDataIssue:
    symbol: str
    message_zh: str


@dataclass(frozen=True)
class AdaptedMarket:
    daily_bars: Mapping[str, tuple[Bar, ...]]
    execution_bars: Mapping[str, tuple[ExecutionBar, ...]]
    calendar: TradingCalendar
    issues: tuple[LegacyDataIssue, ...]
    adjustment_basis: str
    data_as_of: date | None
    amount_is_estimated: bool = False
    availability_is_unknown: bool = False


def adapt_legacy_frames(
    frames: Mapping[str, pd.DataFrame], *, adjustment_basis: str,
    source: str, flags: Mapping[str, pd.DataFrame] | None = None,
) -> AdaptedMarket:
    if not adjustment_basis.strip():
        raise ValueError("必须明确选择复权方式")
    if not source.strip():
        raise ValueError("必须指定数据来源")
    aliases = {'qfq': 'forward', 'hfq': 'backward', 'none': 'unadjusted'}
    normalized_basis = aliases.get(adjustment_basis, adjustment_basis)
    if normalized_basis not in {'forward', 'backward', 'unadjusted'}:
        raise ValueError('无法识别复权方式')
    if source == 'v7_cache' and normalized_basis != 'forward':
        raise ValueError('旧版日线缓存只支持前复权，不能按其他复权方式计算')
    daily: dict[str, tuple[Bar, ...]] = {}
    execution: dict[str, tuple[ExecutionBar, ...]] = {}
    issues: list[LegacyDataIssue] = []
    sessions: set[date] = set()
    amount_is_estimated = False
    availability_is_unknown = False
    required = {"open", "high", "low", "close", "volume"}
    for symbol, original in frames.items():
        try:
            frame = original.copy(deep=True)
            absent = sorted(required.difference(frame.columns))
            if absent:
                raise ValueError("缺少行情字段：" + "、".join(absent))
            if frame.empty:
                raise ValueError("没有行情数据")
            dates = pd.to_datetime(frame.index, errors="coerce")
            if dates.isna().any():
                raise ValueError("日期索引含无效日期")
            if dates.tz is not None:
                dates = dates.tz_convert(SHANGHAI)
            if len({item.date() for item in dates}) != len(dates):
                raise ValueError("日期索引含重复交易日")
            order = sorted(range(len(dates)), key=lambda pos: dates[pos])
            converted: list[Bar] = []
            available: list[ExecutionBar] = []
            symbol_amount_estimated = "amount" not in frame
            symbol_availability_unknown = flags is None or symbol not in flags
            for pos in order:
                row = frame.iloc[pos]
                day = dates[pos].date()
                values = {key: float(row[key]) for key in required}
                amount = float(row["amount"]) if not symbol_amount_estimated else values["close"] * values["volume"]
                bar = Bar(code=symbol, timestamp=datetime.combine(day, time(15), tzinfo=SHANGHAI),
                          amount=amount, source=source, **values)
                converted.append(bar)
                row_flags = {}
                if not symbol_availability_unknown:
                    provided = flags[symbol]
                    if day in provided.index:
                        row_flags = {key: bool(provided.loc[day, key]) for key in
                                     ("is_suspended", "at_limit_up", "at_limit_down") if key in provided.columns}
                available.append(ExecutionBar(bar=Bar(code=symbol,
                    timestamp=datetime.combine(day, time(9, 30), tzinfo=SHANGHAI),
                    amount=amount, source=source, **values), **row_flags))
            daily[symbol] = tuple(converted)
            execution[symbol] = tuple(available)
            sessions.update(item.timestamp.date() for item in converted)
            amount_is_estimated |= symbol_amount_estimated
            availability_is_unknown |= symbol_availability_unknown
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            issues.append(LegacyDataIssue(symbol, f"{symbol} 数据转换失败：{exc}"))
    return AdaptedMarket(daily, execution, TradingCalendar(tuple(sorted(sessions))),
                         tuple(issues), normalized_basis, max(sessions) if sessions else None,
                         amount_is_estimated, availability_is_unknown)
