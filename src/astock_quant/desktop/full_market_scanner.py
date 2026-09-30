"""Durable, per-symbol market-wide screening using the existing September rule 1."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime
import json
import os
from pathlib import Path
from typing import Callable
from uuid import uuid4

import pandas as pd

from .weekly_trend_scanner import ScreenRow, _closed_week_calendar, _three_tier_row
from .weekly_trend_updater import merge_history, read_history, REQUIRED


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class FullMarketResult:
    target: date
    source: str
    total: int
    completed: int
    excluded: int
    failed: int
    selected: int
    paused: bool
    rows: tuple[ScreenRow, ...]
    universe_verified: bool = True
    universe_as_of: str = ""


class FullMarketScanner:
    def __init__(self, app_dir: Path, *, universe_loader: Callable,
                 history_fetcher: Callable[[str], pd.DataFrame], minimum_pool: int = 5000):
        self.app_dir = Path(app_dir)
        self.universe_loader = universe_loader
        self.history_fetcher = history_fetcher
        self.minimum_pool = minimum_pool
        self.active_target: date | None = None
        self.root = self.app_dir / 'v8_runs' / 'screens' / 'full_market'

    def _run_dir(self, target: date) -> Path:
        return self.root / target.isoformat()

    def _manifest(self, target: date) -> dict:
        manifest_path = self._run_dir(target) / 'manifest.json'
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if manifest.get('target') != target.isoformat():
                raise ValueError('扫描快照日期不一致')
            return manifest
        verified, universe_as_of = True, target.isoformat()
        try:
            stocks, source = self.universe_loader()
            self._validate_pool(stocks, source)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            fallback = self._recent_verified_manifest(target)
            if fallback is None:
                raise ValueError(f'全A股列表不完整：{exc}；没有七天内可用的完整名册，未开始检测') from exc
            stocks = fallback['stocks']
            verified, universe_as_of = False, fallback['target']
            source = f"名册待更新：使用{universe_as_of}已核实完整列表；在线补齐失败：{exc}"
        stocks = sorted(stocks, key=lambda item: str(item['code']))
        manifest = {'target': target.isoformat(), 'source': source, 'stocks': stocks,
                    'created_at': datetime.now().isoformat(timespec='seconds'),
                    'rule': '9月8日规则1', 'adjustment_basis': 'qfq',
                    'universe_verified': verified, 'universe_as_of': universe_as_of}
        _atomic_json(manifest_path, manifest)
        return manifest

    def _validate_pool(self, stocks, source):
        codes = [str(item['code']) for item in stocks]
        exchanges = {str(item.get('exchange', '')) for item in stocks}
        valid = (len(stocks) >= self.minimum_pool and len(set(codes)) == len(codes)
                 and {'沪','深','北'} <= exchanges
                 and all(len(code)==6 and code.isdigit() for code in codes)
                 and all(item.get('name') for item in stocks))
        if self.minimum_pool >= 5000:
            valid = valid and all(sum(item.get('exchange')==market for item in stocks)>=minimum
                                 for market,minimum in (('沪',1000),('深',1000),('北',100)))
        if not valid or source.startswith('过期'):
            raise ValueError(f'全A股列表不完整（{len(stocks)}只、覆盖{sorted(exchanges)}）；来源 {source}')

    def _recent_verified_manifest(self, target):
        for path in sorted(self.root.glob('*/manifest.json'), reverse=True):
            try:
                manifest = json.loads(path.read_text(encoding='utf-8'))
                old_date = date.fromisoformat(manifest['target'])
                if not 0 <= (target-old_date).days <= 7 or not manifest.get('universe_verified',True):
                    continue
                if '名册待更新' in manifest['source']:
                    continue
                self._validate_pool(manifest['stocks'], manifest['source'])
                return manifest
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return None

    def _history(self, code: str, target: date) -> pd.DataFrame:
        base_path = self.app_dir / 'cache' / f'{code}.csv'
        update_path = self.app_dir / 'v8_market_updates' / f'{code}.csv'
        base = read_history(base_path) if base_path.exists() else None
        overlay = read_history(update_path) if update_path.exists() else None
        if overlay is not None and base is not None:
            current = merge_history(base, overlay)
        else:
            current = overlay if overlay is not None else base
        if current is not None and current.index[-1].date() >= target:
            return current
        fresh = self.history_fetcher(code)
        if not isinstance(fresh, pd.DataFrame) or fresh.empty:
            raise ValueError('数据源未返回日线')
        fresh = fresh.copy().sort_index()
        fresh.index = pd.to_datetime(fresh.index, errors='raise')
        if fresh.index.has_duplicates or not REQUIRED <= set(fresh.columns):
            raise ValueError('行情列缺失或日期重复')
        if fresh.index[-1].date() < target:
            raise ValueError(f'数据源最新日期仅到 {fresh.index[-1].date()}')
        if base is not None:
            merged = merge_history(base, fresh)
        else:
            merged = fresh
        update_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = update_path.with_name('.' + uuid4().hex + '.tmp')
        try:
            with temporary.open('w', encoding='utf-8', newline='') as output:
                fresh.to_csv(output, index_label='date')
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, update_path)
        finally:
            temporary.unlink(missing_ok=True)
        return merged

    def _rows(self, target: date, stocks: list[dict]) -> list[ScreenRow]:
        folder = self._run_dir(target) / 'rows'
        rows = []
        for stock in stocks:
            path = folder / (stock['code'] + '.json')
            if path.exists():
                raw = json.loads(path.read_text(encoding='utf-8'))
                rows.append(ScreenRow(**{**raw, 'checks': tuple(raw['checks'])}))
        return rows

    def _result(self, target: date, manifest: dict, paused: bool) -> FullMarketResult:
        stocks = manifest['stocks']
        rows = self._rows(target, stocks)
        order = {'strong': 0, 'confirm': 1, 'preconfirm': 2, 'rejected': 3,
                 'insufficient': 4, 'excluded': 5, 'stale': 6, 'error': 7}
        rows.sort(key=lambda row: (order.get(row.status, 7), row.symbol))
        return FullMarketResult(target, manifest['source'], len(stocks), len(rows),
            sum(row.status == 'excluded' for row in rows),
            sum(row.status in ('error', 'stale') for row in rows),
            sum(row.status in ('strong', 'confirm', 'preconfirm') for row in rows),
            paused, tuple(rows), manifest.get('universe_verified',True),
            manifest.get('universe_as_of',target.isoformat()))

    def scan(self, *, target: date, progress: Callable[[int, str], None] | None = None,
             should_pause: Callable[[], bool] | None = None) -> FullMarketResult:
        self.active_target = target
        manifest = self._manifest(target)
        stocks = manifest['stocks']
        folder = self._run_dir(target) / 'rows'
        for index, stock in enumerate(stocks):
            if should_pause and should_pause():
                return self._result(target, manifest, True)
            code, name = stock['code'], stock['name']
            path = folder / (code + '.json')
            if path.exists():
                saved = json.loads(path.read_text(encoding='utf-8'))
                if saved['status'] not in ('error', 'stale'):
                    if progress:
                        progress(index + 1, f'已检查 {index + 1}/{len(stocks)}；{code} 已保存')
                    continue
            if 'ST' in name.upper().replace(' ', '') or '退' in name:
                row = ScreenRow(code, name, 'excluded', '', None, '', 'ST或退市股票，策略排除', ())
            else:
                try:
                    frame = self._history(code, target)
                    days = {stamp.date() for stamp in frame.index if stamp.date() <= target}
                    visible = frame[frame.index.date <= target]
                    weeks = visible.resample('W-FRI').last().dropna()
                    if target.weekday() < 4 and len(weeks):
                        weeks = weeks.iloc[:-1]
                    if len(weeks) < 21:
                        row = ScreenRow(code, name, 'insufficient', visible.index[-1].date().isoformat(),
                            float(visible.close.iloc[-1]), '',
                            f'已取得{len(visible)}行日线、{len(weeks)}个完整周；规则1需至少21个完整周', ())
                    else:
                        row = _three_tier_row(code, frame, target,
                            _closed_week_calendar(days, target), 'qfq', name)
                except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, RuntimeError) as exc:
                    row = ScreenRow(code, name, 'error', '', None, '', f'行情或筛选失败：{exc}', ())
            _atomic_json(path, asdict(row))
            if progress:
                progress(index + 1, f'已检查 {index + 1}/{len(stocks)}；{code} {row.status}')
        result = self._result(target, manifest, False)
        _atomic_json(self.root / 'latest.json', {'target': target.isoformat()})
        return result

    def open_last(self) -> FullMarketResult:
        try:
            target = date.fromisoformat(json.loads((self.root / 'latest.json').read_text(encoding='utf-8'))['target'])
            manifest = json.loads((self._run_dir(target) / 'manifest.json').read_text(encoding='utf-8'))
            return self._result(target, manifest, False)
        except (OSError, ValueError, KeyError) as exc:
            raise ValueError('没有已完成的全市场检测结果') from exc

    def export_csv(self, path: Path) -> Path:
        result = self.open_last()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8-sig', newline='') as output:
            writer = csv.writer(output)
            writer.writerow(['股票代码', '股票简称', '状态', '行情日期', '收盘价', '规则', '原因'])
            for row in result.rows:
                writer.writerow([row.symbol, row.name, row.status, row.latest_date,
                                 row.close if row.close is not None else '', row.setup, row.reason_zh])
        return path
