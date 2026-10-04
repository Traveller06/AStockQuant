"""Causal weekly-strategy screening of the existing read-only daily cache."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
import re
from typing import Callable, Mapping
from uuid import uuid4

import pandas as pd

from astock_quant.data.calendar import SHANGHAI, TradingCalendar, previous_open_day
from astock_quant.core.errors import AStockQuantError
from astock_quant.strategies.weekly_trend.models import PatternState, PatternStatus
from astock_quant.strategies.weekly_trend.strategy import WeeklyTrendConfirmationStrategy

from .legacy_adapter import adapt_legacy_frames


@dataclass(frozen=True)
class ScreenRow:
    symbol: str
    name: str
    status: str
    latest_date: str
    close: float | None
    setup: str
    reason_zh: str
    checks: tuple[Mapping[str, object], ...]
    signal_id: str | None = None


@dataclass(frozen=True)
class ScreenResult:
    data_as_of: date
    generated_at: str
    pool_size: int
    fresh_count: int
    signal_count: int
    watch_count: int
    error_count: int
    adjustment_basis: str
    rows: tuple[ScreenRow, ...]
    pool_label: str = '本地已缓存股票池'


def _safe_date(now: datetime | None = None) -> date:
    local = now.astimezone(SHANGHAI) if now else datetime.now(SHANGHAI)
    cutoff = local.date() if local.time() >= time(15, 30) else local.date() - timedelta(days=1)
    return previous_open_day(cutoff)


def _closed_week_calendar(sessions: set[date], target: date) -> TradingCalendar:
    # The final cached session on Monday–Thursday is not the end of that week.
    # A future Friday is a calendar marker only; it is never used as price data.
    days = set(sessions)
    if target.weekday() < 4:
        days.add(target + timedelta(days=4 - target.weekday()))
    return TradingCalendar(tuple(sorted(days)))


def _row(symbol: str, frame: pd.DataFrame, as_of: date, calendar: TradingCalendar,
         adjustment_basis: str, name: str) -> ScreenRow:
    # All data is copied by the v7 adapter and converted to market-close timestamps.
    market = adapt_legacy_frames({symbol: frame}, adjustment_basis=adjustment_basis, source='v7_cache')
    if market.issues:
        return ScreenRow(symbol, name, 'error', '', None, '', market.issues[0].message_zh, ())
    bars = tuple(bar for bar in market.daily_bars[symbol] if bar.timestamp.date() <= as_of)
    if not bars:
        return ScreenRow(symbol, name, 'stale', '', None, '', '截止日之前没有有效行情', ())
    last = bars[-1]
    if last.timestamp.date() < as_of:
        return ScreenRow(symbol, name, 'stale', last.timestamp.date().isoformat(), last.close,
                         '', '最新行情早于筛选截止日，未用于当期筛选', ())
    strategy = WeeklyTrendConfirmationStrategy()
    state = PatternState(symbol, PatternStatus.INACTIVE, None, None, None, None,
                         strategy.strategy_version, strategy.config.parameter_version,
                         bars[0].timestamp)
    decision = None
    signal = None
    # Any setup's validity ends after at most 20 observed sessions. A few extra
    # days allow trend checks to see the state before it becomes active.
    for index in range(max(0, len(bars) - strategy.config.setup_valid_sessions - 20), len(bars)):
        bar = bars[index]
        visible = bars[: index + 1]
        try:
            evaluation = strategy.evaluate(source_run_id='weekly_screen', daily_bars=visible,
                adjustment_basis=market.adjustment_basis, calendar=calendar, as_of=bar.timestamp,
                state=state)
        except (ValueError, AStockQuantError) as exc:
            # Early bars may have no completed exchange week yet. Other errors
            # are recorded per symbol rather than becoming apparent buy signals.
            if 'at least one completed week' in str(exc):
                continue
            return ScreenRow(symbol, name, 'error', last.timestamp.date().isoformat(), last.close,
                             '', f'策略评估失败：{exc}', ())
        state = evaluation.next_state
        decision, signal = evaluation.decision, evaluation.signal
    if decision is None:
        return ScreenRow(symbol, name, 'rejected', last.timestamp.date().isoformat(), last.close,
                         '', '完整周线数据不足，无法判断趋势', ())
    if signal is not None:
        status = 'signal'
    elif state.status is PatternStatus.WAITING_CONFIRMATION and decision.trend.qualified:
        status = 'watch'
    else:
        status = 'rejected'
    active_setup = state.setup if status == 'watch' else decision.setups.selected
    checks = tuple({'code': item.code, 'passed': item.passed, 'actual': item.actual,
                    'threshold': item.threshold, 'reason_zh': item.reason_zh}
                   for item in decision.all_checks)
    return ScreenRow(symbol, name, status, last.timestamp.date().isoformat(), last.close,
                     active_setup.kind.value if active_setup else '', decision.reason_zh,
                     checks, signal.signal_id if signal else None)


def classify_rule1_daily(frame: pd.DataFrame, *, weekly_candidate: bool) -> str:
    """9 September 8 rule 1: previous closed session only; volume is an upgrade."""
    if not weekly_candidate or len(frame) < 21:
        return 'rejected'
    current, previous = frame.iloc[-1], frame.iloc[-2]
    ma5 = frame.close.iloc[-5:].mean()
    ma20 = frame.close.iloc[-20:].mean()
    above = current.close > ma5 and current.close > ma20
    engulf = (previous.close < previous.open and current.close > current.open
              and current.open <= previous.close and current.close >= previous.open)
    if not (above and engulf):
        return 'preconfirm'
    prior_volume = frame.volume.iloc[-6:-1].mean()
    return 'strong' if current.volume > prior_volume else 'confirm'


def _legacy_candidate(bars: pd.DataFrame, target: date) -> bool:
    """Preserve the v4.3/v7 rule 1 weekly trend calculation and 21-session window."""
    if len(bars) < 21:
        return False
    weekly = bars.resample('W-FRI').agg({'open':'first', 'high':'max', 'low':'min',
                                         'close':'last', 'volume':'sum'}).dropna()
    # A Monday–Thursday partial week cannot establish a weekly setup.
    if target.weekday() < 4 and len(weekly):
        weekly = weekly.iloc[:-1]
    for n in (5, 10, 20):
        weekly[f'ma{n}'] = weekly.close.rolling(n).mean()
    if len(weekly) < 21:
        return False
    swing_high = (weekly.high == weekly.high.rolling(5, center=True).max()).fillna(False).to_numpy()
    swing_low = (weekly.low == weekly.low.rolling(5, center=True).min()).fillna(False).to_numpy()
    highs = [float(weekly.high.iloc[k]) for k in range(2, min(19, len(weekly)-2)) if swing_high[k]]
    lows = [float(weekly.low.iloc[k]) for k in range(2, min(19, len(weekly)-2)) if swing_low[k]]
    candidates: list[date] = []
    for j in range(20, len(weekly)):
        current, previous = weekly.iloc[j], weekly.iloc[j-1]
        confirmed = j-2
        if j > 20 and swing_high[confirmed]:
            highs.append(float(weekly.high.iloc[confirmed]))
        if j > 20 and swing_low[confirmed]:
            lows.append(float(weekly.low.iloc[confirmed]))
        waves = (len(highs) >= 2 and len(lows) >= 2 and
                 highs[-1] > highs[-2] and lows[-1] > lows[-2])
        trend = (current.ma5 > current.ma10 > current.ma20 and
                 current.ma5 > previous.ma5 and current.ma10 > previous.ma10 and
                 current.ma20 > previous.ma20 and
                 (weekly.close.iloc[j-1:j+1] > weekly.ma20.iloc[j-1:j+1]).all() and waves)
        if trend:
            candidates.append(weekly.index[j].date())
    if not candidates:
        return False
    recent_sessions = set(bars.index[-21:].date)
    return any(day in recent_sessions or
               # A Friday holiday can close the week on Thursday.
               any(0 <= (day - session).days <= 3 for session in recent_sessions)
               for day in candidates)


def _three_tier_row(symbol: str, frame: pd.DataFrame, as_of: date,
                    calendar: TradingCalendar, adjustment_basis: str, name: str) -> ScreenRow:
    market = adapt_legacy_frames({symbol: frame}, adjustment_basis=adjustment_basis, source='v7_cache')
    if market.issues:
        return ScreenRow(symbol, name, 'error', '', None, '', market.issues[0].message_zh, ())
    visible = tuple(bar for bar in market.daily_bars[symbol] if bar.timestamp.date() <= as_of)
    if not visible:
        return ScreenRow(symbol, name, 'stale', '', None, '', '截止日之前没有有效行情', ())
    last = visible[-1]
    stamp = last.timestamp.date().isoformat()
    if last.timestamp.date() < as_of:
        return ScreenRow(symbol, name, 'stale', stamp, last.close, '', '行情早于统一筛选截止日', ())
    daily = pd.DataFrame(({'open': b.open, 'high': b.high, 'low': b.low,
                           'close': b.close, 'volume': b.volume} for b in visible),
                         index=pd.DatetimeIndex([b.timestamp.date() for b in visible]))
    candidate = _legacy_candidate(daily, as_of)
    status = classify_rule1_daily(daily, weekly_candidate=candidate)
    checks = ({'code': 'legacy.weekly_candidate', 'passed': candidate,
               'actual': str(candidate), 'threshold': '20交易日内周线多头候选',
               'reason_zh': '9月8日规则1周线候选'},
              {'code': 'legacy.daily_rule1', 'passed': status in ('confirm','strong'),
               'actual': status, 'threshold': '收盘站上MA5/MA20且阳包阴',
               'reason_zh': '日线买入观察'},
              {'code': 'legacy.volume', 'passed': status == 'strong',
               'actual': str(float(daily.volume.iloc[-1])),
               'threshold': '高于前5交易日平均成交量', 'reason_zh': '放量强确认'})
    explanations = {'preconfirm': '周线候选有效，等待日线站上均线且阳包阴',
                    'confirm': '日线确认成立；下一交易日核实可成交性',
                    'strong': '日线确认且同日放量；下一交易日核实可成交性',
                    'rejected': '尚无有效周线候选'}
    return ScreenRow(symbol, name, status, stamp, last.close,
                     '9月8日规则1' if candidate else '', explanations[status], checks)


def _result(rows: list[ScreenRow], as_of: date, adjustment_basis: str) -> ScreenResult:
    order = {'strong': 0, 'confirm': 1, 'preconfirm': 2,
             'signal': 0, 'watch': 1, 'rejected': 3, 'stale': 4, 'error': 5}
    ordered = tuple(sorted(rows, key=lambda row: (order[row.status], row.symbol)))
    return ScreenResult(as_of, datetime.now(SHANGHAI).isoformat(), len(ordered),
        sum(row.status not in ('stale', 'error') for row in ordered),
        sum(row.status in ('signal', 'confirm', 'strong') for row in ordered),
        sum(row.status in ('watch', 'preconfirm') for row in ordered),
        sum(row.status == 'error' for row in ordered), adjustment_basis, ordered)


def scan_weekly_frames(frames: Mapping[str, pd.DataFrame], *, adjustment_basis: str,
                       as_of: date | None = None, names: Mapping[str, str] | None = None,
                       now: datetime | None = None,
                       progress: Callable[[int, str], None] | None = None) -> ScreenResult:
    if not adjustment_basis.strip():
        raise ValueError('必须明确选择复权方式')
    cutoff = min(as_of, _safe_date(now)) if as_of else _safe_date(now)
    sessions = set()
    for frame in frames.values():
        try:
            sessions.update(item.date() for item in pd.to_datetime(frame.index, errors='coerce')
                            if not pd.isna(item) and item.date() <= cutoff)
        except (TypeError, ValueError, AttributeError):
            continue
    if not sessions:
        raise ValueError('本地缓存中没有已收盘的有效交易日；请先准备历史行情')
    target = max(day for day in sessions if day <= cutoff)
    calendar = _closed_week_calendar(sessions, target)
    rows = []
    for index, (symbol, frame) in enumerate(sorted(frames.items())):
        try:
            row = _row(symbol, frame, target, calendar, adjustment_basis,
                       (names or {}).get(symbol, symbol))
        except (ValueError, TypeError, KeyError, AttributeError, AStockQuantError) as exc:
            row = ScreenRow(symbol, (names or {}).get(symbol, symbol), 'error', '',
                            None, '', f'股票数据处理失败：{exc}', ())
        rows.append(row)
        if progress:
            progress(int((index + 1) * 100 / len(frames)), f'已筛选 {index + 1}/{len(frames)} 只')
    return _result(rows, target, adjustment_basis)


class WeeklyTrendScanner:
    def __init__(self, app_dir: Path, *, three_tier: bool = False):
        self.app_dir = Path(app_dir)
        self.screen_dir = self.app_dir / 'v8_runs' / 'screens'
        self.three_tier = three_tier

    @property
    def _screen_file(self) -> Path:
        return self.screen_dir / ('latest_three_tier.json' if self.three_tier else 'latest_screen.json')

    def scan_cache(self, *, adjustment_basis: str, as_of: date | None = None,
                   progress: Callable[[int, str], None] | None = None) -> ScreenResult:
        if not adjustment_basis.strip():
            raise ValueError('必须明确选择复权方式')
        files = sorted(path for path in (self.app_dir / 'cache').glob('*.csv')
                       if re.fullmatch(r'\d{6}\.csv', path.name) and path.is_file())
        if not files:
            raise ValueError('没有本地股票日线缓存；请先使用“研究样本与数据准备”下载行情')
        cutoff = min(as_of, _safe_date()) if as_of else _safe_date()
        names = self._names()
        dates = set()
        for path in files:
            try:
                column = pd.read_csv(path, usecols=['date'])['date']
                dates.update(item.date() for item in pd.to_datetime(column, errors='coerce')
                             if not pd.isna(item) and item.date() <= cutoff)
            except (OSError, ValueError, KeyError):
                continue
        if not dates:
            raise ValueError('缓存中没有已收盘的有效交易日，请更新行情后再筛选')
        # Never relabel the newest *available* historical date as today's close.
        # Holidays can be chosen explicitly; without an exchange calendar the
        # latest weekday is a conservative target and missing bars stay stale.
        target = cutoff
        calendar = _closed_week_calendar(dates, target)
        rows = []
        for index, path in enumerate(files):
            code = path.stem
            try:
                frame = pd.read_csv(path, parse_dates=['date']).set_index('date')
                update = self.app_dir / 'v8_market_updates' / path.name
                if update.is_file():
                    from .weekly_trend_updater import merge_history, read_history
                    frame = merge_history(frame, read_history(update))
                evaluator = _three_tier_row if self.three_tier else _row
                row = evaluator(code, frame, target, calendar, adjustment_basis, names.get(code, code))
            except (OSError, ValueError, TypeError, KeyError, AttributeError, AStockQuantError) as exc:
                row = ScreenRow(code, names.get(code, code), 'error', '', None, '',
                                f'读取本地行情失败：{exc}', ())
            rows.append(row)
            if progress:
                progress(int((index + 1) * 100 / len(files)), f'已筛选 {index + 1}/{len(files)} 只')
        result = _result(rows, target, adjustment_basis)
        self._save(result)
        return result

    def _names(self) -> dict[str, str]:
        universe = self.app_dir / 'a_share_universe.json'
        try:
            stocks = json.loads(universe.read_text(encoding='utf-8')).get('stocks', [])
            return {str(item['code']).zfill(6): str(item['name']) for item in stocks
                    if isinstance(item, dict) and 'code' in item and 'name' in item}
        except (OSError, ValueError, TypeError, KeyError):
            return {}

    def _save(self, result: ScreenResult) -> None:
        self.screen_dir.mkdir(parents=True, exist_ok=True)
        output = self._screen_file
        temporary = self.screen_dir / f'.{uuid4().hex}.tmp'
        try:
            with temporary.open('w', encoding='utf-8') as target:
                payload = asdict(result)
                payload['data_as_of'] = result.data_as_of.isoformat()
                json.dump(payload, target, ensure_ascii=False, indent=2)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)

    def open_last_screen(self) -> ScreenResult:
        try:
            raw = json.loads(self._screen_file.read_text(encoding='utf-8'))
            rows = tuple(ScreenRow(**{**item, 'checks': tuple(item['checks'])}) for item in raw['rows'])
            return ScreenResult(date.fromisoformat(raw['data_as_of']), raw['generated_at'],
                raw['pool_size'], raw['fresh_count'], raw['signal_count'], raw['watch_count'],
                raw['error_count'], raw['adjustment_basis'], rows, raw['pool_label'])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ValueError('没有可打开的完整筛选结果；请重新筛选') from exc

    def export_csv(self, destination: Path) -> Path:
        result = self.open_last_screen()
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('w', encoding='utf-8-sig', newline='') as output:
            writer = csv.writer(output)
            writer.writerow(['股票代码','股票简称','筛选状态','行情日期','收盘价','形态','筛选说明','信号ID'])
            for row in result.rows:
                labels = {'preconfirm': '预确认', 'confirm': '确认', 'strong': '强确认',
                          'signal': '当日确认', 'watch': '等待确认', 'stale': '行情过期',
                          'rejected': '未入选', 'error': '数据错误'}
                writer.writerow([row.symbol, row.name, labels.get(row.status, row.status), row.latest_date,
                                 row.close if row.close is not None else '', row.setup,
                                 row.reason_zh, row.signal_id or ''])
        return destination
