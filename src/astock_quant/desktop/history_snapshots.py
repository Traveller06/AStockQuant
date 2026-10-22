"""Validated independent qfq history; immutable local snapshots, never legacy writes."""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import uuid4

import numpy as np
import pandas as pd

from .weekly_trend_updater import REQUIRED, read_history


def validate_history(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty or not REQUIRED <= set(frame.columns):
        raise ValueError('行情为空或缺少OHLCV字段')
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError('行情必须使用日期时间索引')
    if (frame.index.hasnans or frame.index.has_duplicates or frame.index.tz is not None
            or not frame.index.equals(frame.index.normalize())):
        raise ValueError('行情日期无效、重复或不是日线日期')
    result = frame.copy().sort_index()
    columns = ['open', 'high', 'low', 'close', 'volume']
    values = result[columns].apply(pd.to_numeric, errors='raise').astype(float)
    if not np.isfinite(values.to_numpy()).all():
        raise ValueError('行情包含空值或非有限数值')
    prices = values[['open', 'high', 'low', 'close']]
    if (prices <= 0).any().any() or (values.volume < 0).any():
        raise ValueError('OHLC价格必须为正且成交量不能为负')
    if ((values.high < prices.max(axis=1)) | (values.low > prices.min(axis=1))).any():
        raise ValueError('行情最高价或最低价不符合OHLC关系')
    result[columns] = values
    return result


class HistorySnapshots:
    def __init__(self, app_dir: Path, code: str):
        if not re.fullmatch(r'\d{6}', code):
            raise ValueError('无效股票代码')
        self.code = code
        self.folder = Path(app_dir) / 'v8_history_snapshots' / code

    def load(self) -> pd.DataFrame | None:
        candidates = []
        for manifest in self.folder.glob('*.json'):
            try:
                info = json.loads(manifest.read_text(encoding='utf8'))
                if (info['schema'] != 1 or info['symbol'] != self.code
                        or info['adjustment_basis'] != 'qfq'):
                    continue
                csv_path = manifest.with_suffix('.csv')
                if hashlib.sha256(csv_path.read_bytes()).hexdigest() != info['sha256']:
                    continue
                frame = validate_history(read_history(csv_path))
                if (len(frame) != info['rows'] or frame.index[0].date().isoformat() != info['first_date']
                        or frame.index[-1].date().isoformat() != info['last_date']):
                    continue
                candidates.append((frame.index[-1], manifest.name, frame))
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                continue
        return max(candidates, key=lambda item: item[:2])[2] if candidates else None

    def save(self, frame: pd.DataFrame, *, target: date, reason: str, source: str) -> None:
        frame = validate_history(frame)
        self.folder.mkdir(parents=True, exist_ok=True)
        name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid4().hex
        csv_path = self.folder / (name + '.csv')
        # Unique exclusive writes: interrupted snapshots have no valid metadata and are ignored.
        with csv_path.open('x', encoding='utf8', newline='') as output:
            frame.to_csv(output, index_label='date')
            output.flush()
            os.fsync(output.fileno())
        info = {'schema': 1, 'symbol': self.code, 'adjustment_basis': 'qfq',
                'rows': len(frame), 'first_date': frame.index[0].date().isoformat(),
                'last_date': frame.index[-1].date().isoformat(), 'target': target.isoformat(),
                'source': source, 'reason': reason,
                'sha256': hashlib.sha256(csv_path.read_bytes()).hexdigest()}
        with csv_path.with_suffix('.json').open('x', encoding='utf8') as output:
            json.dump(info, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
