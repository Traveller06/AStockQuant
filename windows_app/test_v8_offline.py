"""Offline smoke test shipped with the Windows program."""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from astock_quant.desktop.weekly_trend_facade import DesktopBacktestOptions, WeeklyTrendFacade


class V8OfflineTests(unittest.TestCase):
    def test_run_and_reopen_audit(self):
        dates = pd.bdate_range('2025-01-02', periods=90)
        frame = pd.DataFrame({'open':[10.]*90, 'high':[11.]*90, 'low':[9.]*90,
                              'close':[10.]*90, 'volume':[1000.]*90}, index=dates)
        with tempfile.TemporaryDirectory() as temporary:
            facade = WeeklyTrendFacade(Path(temporary), '8.0.0')
            result = facade.run({'600000': frame}, DesktopBacktestOptions.defaults())
            self.assertTrue((result.run_dir / '_COMPLETE').exists())
            self.assertEqual(facade.open_last_result().run_id, result.run_id)


if __name__ == '__main__':
    unittest.main()
