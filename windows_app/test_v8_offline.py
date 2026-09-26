"""Offline smoke test shipped with the Windows program."""

import tempfile
import unittest
from unittest.mock import patch
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from astock_quant.desktop.weekly_trend_facade import DesktopBacktestOptions, WeeklyTrendFacade
from astock_quant.desktop.weekly_trend_scanner import WeeklyTrendScanner
from astock_quant.desktop.weekly_trend_updater import CachedHistoryUpdater
from astock_quant.desktop.full_market_scanner import FullMarketScanner


class V8OfflineTests(unittest.TestCase):
    def test_short_stock_history_is_recorded_without_ending_market_scan(self):
        days = pd.bdate_range(end='2026-09-25', periods=180)
        frame = pd.DataFrame({'open': [10.]*180, 'high': [11.]*180,
                              'low': [9.]*180, 'close': [10.]*180,
                              'volume': [100.]*180}, index=days)
        stocks = [{'code': code, 'name': name, 'exchange': market}
                  for code, name, market in (('000001','深市','深'), ('430001','北交','北'),
                                             ('600000','沪市','沪'))]

        def fetch(code):
            if code == '000001':
                raise RuntimeError('腾讯:有效历史行情不足：38行')
            return frame

        with tempfile.TemporaryDirectory() as temporary:
            scanner = FullMarketScanner(Path(temporary),
                universe_loader=lambda: (stocks, '完整离线名单'),
                history_fetcher=fetch, minimum_pool=3)
            result = scanner.scan(target=days[-1].date())
            self.assertEqual(result.completed, 3)
            self.assertEqual(result.failed, 1)
            self.assertTrue((Path(temporary) / 'v8_market_updates' / '600000.csv').exists())
            self.assertEqual(scanner.open_last().completed, 3)

    def test_short_index_history_allows_market_date_check_and_stock_gate_stays_120(self):
        try:
            from windows_app import main
        except ImportError:
            import main
        days = pd.bdate_range(end='2026-09-25', periods=38)
        bars = [[day.strftime('%Y-%m-%d'), '10', '10', '11', '9', '100'] for day in days]

        class Response:
            def raise_for_status(self): pass
            def json(self):
                return {'data': {'sh000300': {'qfqday': bars},
                                 'sh600000': {'qfqday': bars}}}

        class Session:
            trust_env = False
            def get(self, *args, **kwargs): return Response()

        with tempfile.TemporaryDirectory() as temp:
            with patch.object(main.requests, 'Session', Session), patch.object(main, 'CACHE_DIR', Path(temp)):
                index = main.fetch_history('INDEX_000300', start_year=2026,
                    market_symbol='sh000300', force_refresh=True, persist=False, min_rows=2)
                self.assertEqual(len(index), 38)
                with self.assertRaisesRegex(RuntimeError, '有效历史行情不足：38行'):
                    main.fetch_history('600000', start_year=2026, force_refresh=True, persist=False)

    def test_full_a_share_scan_resumes_and_preserves_legacy_cache(self):
        days = pd.bdate_range('2025-01-02', periods=320)
        frame = pd.DataFrame({'open': [10.]*320, 'high': [11.]*320,
                              'low': [9.]*320, 'close': [10.]*320,
                              'volume': [100.]*320}, index=days)
        stocks = [{'code': code, 'name': name, 'exchange': market}
                  for code, name, market in (('600000','浦发','沪'), ('000001','平安','深'),
                                             ('430001','北交','北'), ('600001','*ST测试','沪'))]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'cache').mkdir()
            frame.iloc[:-3].to_csv(root / 'cache' / '600000.csv', index_label='date')
            original = (root / 'cache' / '600000.csv').read_bytes()
            fetched = []
            def fetch(code):
                fetched.append(code)
                return frame
            scanner = FullMarketScanner(root, universe_loader=lambda: (stocks,'离线完整股票池'),
                                        history_fetcher=fetch, minimum_pool=3)
            partial = scanner.scan(target=days[-1].date(),
                                   should_pause=lambda: len(fetched) >= 1)
            self.assertTrue(partial.paused)
            result = scanner.scan(target=days[-1].date())
            self.assertEqual((result.total, result.completed, result.excluded), (4,4,1))
            self.assertEqual(len(fetched), 3)
            self.assertEqual((root / 'cache' / '600000.csv').read_bytes(), original)
            self.assertEqual(scanner.open_last().total, 4)

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

    def test_incremental_refresh_keeps_original_cache_and_screen_reads_update(self):
        dates = pd.bdate_range('2025-01-02', periods=320)
        frame = pd.DataFrame({'open':[10.]*320, 'high':[11.]*320,
                              'low':[9.]*320, 'close':[10.]*320,
                              'volume':[100.]*320},index=dates)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'cache').mkdir()
            frame.iloc[:-1].to_csv(root/'cache/600000.csv', index_label='date')
            original=(root/'cache/600000.csv').read_bytes()
            outcome=CachedHistoryUpdater(root).refresh(
                target=dates[-1].date(),fetcher=lambda code: frame)
            self.assertEqual(outcome.updated,1)
            self.assertEqual((root/'cache/600000.csv').read_bytes(),original)
            screen=WeeklyTrendScanner(root,three_tier=True).scan_cache(
                adjustment_basis='qfq',as_of=dates[-1].date())
            self.assertEqual(screen.fresh_count,1)

    def test_run_and_reopen_audit(self):
        dates = pd.bdate_range('2025-01-02', periods=90)
        frame = pd.DataFrame({'open':[10.]*90, 'high':[11.]*90, 'low':[9.]*90,
                              'close':[10.]*90, 'volume':[1000.]*90}, index=dates)
        with tempfile.TemporaryDirectory() as temporary:
            facade = WeeklyTrendFacade(Path(temporary), '8.3.2')
            result = facade.run({'600000': frame}, DesktopBacktestOptions.defaults())
            self.assertTrue((result.run_dir / '_COMPLETE').exists())
            self.assertEqual(facade.open_last_result().run_id, result.run_id)


if __name__ == '__main__':
    unittest.main()
