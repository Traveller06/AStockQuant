"""Incremental stock-pool refresh; legacy daily caches are never written here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import os
from pathlib import Path
import re
from typing import Callable
from uuid import uuid4

import pandas as pd


REQUIRED = {'open', 'high', 'low', 'close', 'volume'}


def read_history(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=['date']).set_index('date').sort_index()
    if frame.empty or not REQUIRED.issubset(frame.columns) or frame.index.has_duplicates:
        raise ValueError('行情列缺失、重复日期或空文件')
    return frame


def merge_history(base: pd.DataFrame, overlay: pd.DataFrame) -> pd.DataFrame:
    """Rebase older qfq prices at the boundary, then prefer refreshed bars."""
    if not REQUIRED.issubset(base.columns) or not REQUIRED.issubset(overlay.columns):
        raise ValueError('更新行情缺少 OHLCV 字段')
    if base.empty or overlay.empty or overlay.index.has_duplicates:
        raise ValueError('更新行情为空或日期重复')
    base, overlay = base.sort_index(), overlay.sort_index()
    common = base.index.intersection(overlay.index)
    if len(common) < 3:
        raise ValueError('新旧行情重叠不足3日，无法核实前复权口径')
    ratios = overlay.loc[common[:3], 'close'].astype(float) / base.loc[common[:3], 'close'].astype(float)
    if (not ratios.notna().all() or (ratios <= 0).any() or
            (ratios.max() / ratios.min() - 1) > .003):
        raise ValueError('新旧行情前复权价格无法在交界处对齐')
    previous = base.loc[base.index < overlay.index[0]].copy()
    previous.loc[:, ['open', 'high', 'low', 'close']] = (
        previous[['open', 'high', 'low', 'close']].astype(float) * float(ratios.median()))
    return pd.concat([previous, overlay]).sort_index()


@dataclass(frozen=True)
class RefreshOutcome:
    total: int
    updated: int
    skipped: int
    failed: int
    paused: bool
    errors: tuple[str, ...]


class CachedHistoryUpdater:
    def __init__(self, app_dir: Path):
        self.app_dir = Path(app_dir)
        self.cache_dir = self.app_dir / 'cache'
        self.update_dir = self.app_dir / 'v8_market_updates'

    def refresh(self, *, target: date, fetcher: Callable[[str], pd.DataFrame],
                progress: Callable[[int, str], None] | None = None,
                should_pause: Callable[[], bool] | None = None) -> RefreshOutcome:
        files = sorted(p for p in self.cache_dir.glob('*.csv')
                       if re.fullmatch(r'\d{6}\.csv', p.name) and p.is_file())
        if not files:
            raise ValueError('本地没有股票日线缓存，请先在数据准备页建立股票池')
        updated = skipped = failed = 0
        errors: list[str] = []
        for index, path in enumerate(files):
            if should_pause and should_pause():
                return RefreshOutcome(len(files), updated, skipped, failed, True, tuple(errors))
            try:
                base = read_history(path)
                overlay_path = self.update_dir / path.name
                overlay = read_history(overlay_path) if overlay_path.exists() else None
                last = max(base.index[-1], overlay.index[-1] if overlay is not None else base.index[-1])
                if last.date() >= target:
                    skipped += 1
                else:
                    fresh = fetcher(path.stem)
                    if not isinstance(fresh, pd.DataFrame) or fresh.empty:
                        raise ValueError('数据源未返回日线')
                    fresh = fresh.copy().sort_index()
                    fresh.index = pd.to_datetime(fresh.index, errors='raise')
                    if fresh.index[-1].date() < target:
                        raise ValueError(f'数据源最新日期仅到 {fresh.index[-1].date()}')
                    merge_history(base, fresh)
                    self.update_dir.mkdir(parents=True, exist_ok=True)
                    temp = self.update_dir / f'.{path.stem}.{uuid4().hex}.tmp'
                    try:
                        with temp.open('w', encoding='utf-8', newline='') as stream:
                            fresh.to_csv(stream, index_label='date')
                            stream.flush()
                            os.fsync(stream.fileno())
                        os.replace(temp, overlay_path)
                    finally:
                        temp.unlink(missing_ok=True)
                    updated += 1
            except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
                failed += 1
                if len(errors) < 100:
                    errors.append(f'{path.stem}：{exc}')
            if progress:
                progress(int(100 * (index + 1) / len(files)),
                         f'行情更新 {index+1}/{len(files)}；新增 {updated}、跳过 {skipped}、失败 {failed}')
        return RefreshOutcome(len(files), updated, skipped, failed, False, tuple(errors))
