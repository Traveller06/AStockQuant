"""Offline smoke test shipped with the Windows program."""

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from astock_quant.desktop.weekly_trend_facade import DesktopBacktestOptions, WeeklyTrendFacade
from astock_quant.desktop.weekly_trend_scanner import WeeklyTrendScanner


class V8OfflineTests(unittest.TestCase):
    def test_cached_stock_pool_produces_a_weekly_watch_and_saves_result(self):
        days = [date(2026, 1, 9) + timedelta(days=7 * index) for index in range(25)]
        closes = [10.0 + index * 0.4 for index in range(25)]
        frame = pd.DataFrame({
            'open': [value - .1 for value in closes],
            'high': [value + (2 if index in (5, 12) else .2) for index, value in enumerate(closes)],
            'low': [value - (2 if index in (7, 14) else .2) for index, value in enumerate(closes)],
            'close': closes, 'volume': [150 if index == 24 else 100 for index in range(25)]
        }, index=pd.to_datetime(days))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'cache').mkdir()
            frame.to_csv(root / 'cache' / '600000.csv', index_label='date')
            scanner = WeeklyTrendScanner(root)
            result = scanner.scan_cache(adjustment_basis='qfq', as_of=days[-1])
            self.assertEqual(result.watch_count, 1)
            self.assertEqual(scanner.open_last_screen().pool_size, 1)
            three_tier = WeeklyTrendScanner(root, three_tier=True)
            graded = three_tier.scan_cache(adjustment_basis='qfq', as_of=days[-1])
            self.assertEqual(graded.rows[0].status, 'preconfirm')
            self.assertEqual(three_tier.open_last_screen().rows, graded.rows)
            self.assertEqual(scanner.open_last_screen().rows, result.rows)

    def test_run_and_reopen_audit(self):
        dates = pd.bdate_range('2025-01-02', periods=90)
        frame = pd.DataFrame({'open':[10.]*90, 'high':[11.]*90, 'low':[9.]*90,
                              'close':[10.]*90, 'volume':[1000.]*90}, index=dates)
        with tempfile.TemporaryDirectory() as temporary:
            facade = WeeklyTrendFacade(Path(temporary), '8.2.0')
            result = facade.run({'600000': frame}, DesktopBacktestOptions.defaults())
            self.assertTrue((result.run_dir / '_COMPLETE').exists())
            self.assertEqual(facade.open_last_result().run_id, result.run_id)


if __name__ == '__main__':
    unittest.main()
