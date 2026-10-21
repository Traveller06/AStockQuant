"""Small desktop API around the v8 backtest and its persisted audit trail."""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
from typing import Callable, Mapping
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

from astock_quant.backtest.engine import BacktestRequest
from astock_quant.backtest.fees import FeeSchedule
from astock_quant.reports.run_store import RunStore, StoredRun
from astock_quant.services.weekly_trend_service import WeeklyTrendService

from .legacy_adapter import adapt_legacy_frames


class DesktopRunError(RuntimeError):
    def __init__(self, stage: str, scope: str, message_zh: str, suggestion_zh: str):
        super().__init__(f"{message_zh}；{suggestion_zh}")
        self.stage = stage
        self.scope = scope
        self.message_zh = message_zh
        self.suggestion_zh = suggestion_zh


@dataclass(frozen=True)
class DesktopBacktestOptions:
    start: date
    end: date
    adjustment_basis: str
    initial_cash: Decimal
    commission_rate: Decimal
    minimum_commission: Decimal
    stamp_tax_rate: Decimal
    slippage_rate: Decimal

    @classmethod
    def defaults(cls) -> DesktopBacktestOptions:
        defaults = FeeSchedule.default()
        return cls(date(2018, 1, 1), date.today(), 'qfq', Decimal('100000'),
                   defaults.commission_rate, defaults.minimum_commission,
                   defaults.stamp_tax_rate, defaults.slippage_rate)


@dataclass(frozen=True)
class DesktopRunSummary:
    run_id: str
    run_dir: Path
    data_as_of: str
    metrics: Mapping[str, str]
    error_count: int
    warning_zh: str
    tables: Mapping[str, tuple[Mapping[str, object], ...]]


def _pct(value: Decimal) -> str:
    return f"{value * 100:.2f}%"


def project_desktop_summary(stored: StoredRun) -> DesktopRunSummary:
    path = stored.path
    tables: dict[str, tuple[Mapping[str, object], ...]] = {}
    for kind in ('signals', 'orders', 'trades', 'decisions', 'checks', 'events', 'errors'):
        value = json.loads((path / f'{kind}.json').read_text(encoding='utf-8'))
        if not isinstance(value, list):
            raise ValueError(f'{kind} is not a list')
        tables[kind] = tuple(value)
    with (path / 'equity.csv').open(encoding='utf-8', newline='') as source:
        equity = tuple(csv.DictReader(source))
    first = Decimal(equity[0]['equity']) if equity else Decimal(stored.manifest.parameters['initial_cash'])
    last = Decimal(equity[-1]['equity']) if equity else first
    peak = first
    drawdown = Decimal(0)
    total_positions = 0
    for row in equity:
        value = Decimal(row['equity'])
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
        total_positions += int(row['position_count'])
    trades = tables['trades']
    # Realized winners require paired fills; report unavailable when the run contains sells.
    metrics = {'收益': _pct(last / first - 1), '最大回撤': _pct(drawdown),
               '交易次数': str(len(trades)), '胜率': '待逐笔配对' if trades else '—',
               '盈亏因子': '待逐笔配对' if trades else '—',
               '平均仓位': '待逐日计算' if total_positions else '0.00%'}
    warning = '旧缓存缺少成交额和停牌/涨跌停状态，成交额为估算值；未核实的可交易性可能影响撮合。'
    return DesktopRunSummary(stored.manifest.run_id, path, stored.manifest.data_cutoff,
                             metrics, len(tables['errors']), warning, tables)


class WeeklyTrendFacade:
    def __init__(self, app_dir: Path, app_version: str):
        self.app_dir = Path(app_dir)
        self.app_version = app_version
        self.store = RunStore(self.app_dir / 'v8_runs')

    def run(self, frames: Mapping[str, pd.DataFrame], options: DesktopBacktestOptions,
            progress: Callable[[int, str], None] | None = None) -> DesktopRunSummary:
        if options.start > options.end:
            raise DesktopRunError('配置', '日期', '开始日期晚于结束日期', '请检查回测日期')
        if progress:
            progress(10, '转换历史行情')
        try:
            market = adapt_legacy_frames({symbol: frame.loc[
                (pd.to_datetime(frame.index) >= pd.Timestamp(options.start)) &
                (pd.to_datetime(frame.index) <= pd.Timestamp(options.end))]
                for symbol, frame in frames.items()},
                adjustment_basis=options.adjustment_basis, source='v7_cache')
            if not market.daily_bars or market.data_as_of is None:
                raise DesktopRunError('数据', '缓存', '没有有效行情可回测', '请先在数据准备页面下载历史行情')
            fees = FeeSchedule(options.commission_rate, options.minimum_commission,
                               options.stamp_tax_rate, options.slippage_rate)
            request = BacktestRequest(market.daily_bars, market.execution_bars, market.calendar,
                                      options.initial_cash, fees, market.adjustment_basis,
                                      market.data_as_of, self.app_version)
            (self.app_dir / 'v8_state').mkdir(parents=True, exist_ok=True)
            if progress:
                progress(40, '运行周线趋势回测')
            result = WeeklyTrendService(self.store).run_backtest(request)
            stored = self.store.open_completed(result.run_id)
            if progress:
                progress(100, '回测完成')
            summary = project_desktop_summary(stored)
            if market.issues:
                details = tuple({'symbol': issue.symbol, 'message_zh': issue.message_zh}
                                for issue in market.issues)
                # Keep adapter errors in the same isolated run, including after a restart.
                self.store.write_json(result.run_id, 'adapter_issues.json', details)
                tables = dict(summary.tables)
                tables['errors'] = summary.tables['errors'] + details
                summary = replace(summary, tables=tables, error_count=len(tables['errors']))
            return summary
        except DesktopRunError:
            raise
        except Exception as exc:
            raise DesktopRunError('运行', '周线策略', f'回测失败：{exc}', '检查行情并重试') from exc

    def open_last_result(self) -> DesktopRunSummary:
        try:
            recent = self.store.list_recent()
            if not recent:
                raise DesktopRunError('读取', '运行记录', '没有已完成回测', '请先运行回测')
            stored = self.store.open_completed(recent[0].manifest.run_id)
            if not WeeklyTrendService.REQUIRED_AUDIT_FILES.issubset(
                {item.name for item in stored.path.iterdir()}):
                raise ValueError('missing audit file')
            summary = project_desktop_summary(stored)
            issues_path = stored.path / 'adapter_issues.json'
            if issues_path.is_file():
                extra = json.loads(issues_path.read_text(encoding='utf-8'))
                tables = dict(summary.tables)
                tables['errors'] = summary.tables['errors'] + tuple(extra)
                summary = replace(summary, tables=tables, error_count=len(tables['errors']))
            return summary
        except DesktopRunError:
            raise
        except Exception as exc:
            raise DesktopRunError('读取', '运行清单', '运行清单损坏或审计数据缺失', '请重新回测') from exc

    def export_audit_bundle(self, destination: Path) -> Path:
        summary = self.open_last_result()
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(destination, 'w', ZIP_DEFLATED) as output:
            optional = {'adapter_issues.json'} if (summary.run_dir / 'adapter_issues.json').is_file() else set()
            for name in sorted(WeeklyTrendService.REQUIRED_AUDIT_FILES | optional):
                output.write(summary.run_dir / name, arcname=name)
        return destination
