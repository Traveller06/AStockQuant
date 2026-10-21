from datetime import date
from pathlib import Path
import zipfile

import pandas as pd
import pytest

from astock_quant.desktop.weekly_trend_facade import DesktopBacktestOptions, DesktopRunError, WeeklyTrendFacade


def _frame():
    dates = pd.bdate_range('2025-01-02', periods=90)
    return pd.DataFrame({'open':[10.]*len(dates), 'high':[11.]*len(dates),
                         'low':[9.]*len(dates), 'close':[10.]*len(dates),
                         'volume':[10000.]*len(dates)}, index=dates)


def test_facade_runs_with_legacy_cache_and_isolates_paths(tmp_path):
    facade = WeeklyTrendFacade(tmp_path, app_version='8.0.0')
    summary = facade.run({'600000':_frame()}, DesktopBacktestOptions.defaults())
    assert summary.run_dir.parent == tmp_path / 'v8_runs'
    assert (summary.run_dir / '_COMPLETE').exists()
    assert summary.metrics.keys() == {'收益', '最大回撤', '交易次数', '胜率', '盈亏因子', '平均仓位'}
    assert not (tmp_path / 'tail_strategy_state.json').exists()
    assert facade.open_last_result().run_id == summary.run_id
    archive = facade.export_audit_bundle(tmp_path / 'audit.zip')
    with zipfile.ZipFile(archive) as bundle:
        assert 'manifest.json' in bundle.namelist()
        assert '_COMPLETE' not in bundle.namelist()


def test_facade_reports_missing_and_corrupt_run_in_chinese(tmp_path):
    facade = WeeklyTrendFacade(tmp_path, app_version='8.0.0')
    with pytest.raises(DesktopRunError, match='回测'):
        facade.open_last_result()
    summary = facade.run({'600000':_frame()}, DesktopBacktestOptions.defaults())
    (summary.run_dir / 'manifest.json').write_text('{', encoding='utf8')
    with pytest.raises(DesktopRunError, match='运行清单.*重新回测'):
        facade.open_last_result()


def test_facade_rejects_empty_market(tmp_path):
    with pytest.raises(DesktopRunError, match='有效行情'):
        WeeklyTrendFacade(tmp_path, app_version='8.0.0').run({}, DesktopBacktestOptions.defaults())


def test_bad_symbol_is_retained_in_run_and_export(tmp_path):
    facade = WeeklyTrendFacade(tmp_path, app_version='8.0.0')
    summary = facade.run({'600000':_frame(), '600001':_frame().drop(columns='open')},
                         DesktopBacktestOptions.defaults())
    assert summary.error_count == 1
    assert summary.tables['errors'][0]['symbol'] == '600001'
    assert facade.open_last_result().error_count == 1
    with zipfile.ZipFile(facade.export_audit_bundle(tmp_path / 'audit.zip')) as bundle:
        assert 'adapter_issues.json' in bundle.namelist()


def test_real_strategy_accepts_v7_forward_adjusted_history(tmp_path):
    frame = _frame()
    dates = pd.bdate_range('2025-01-02', periods=160)
    frame = pd.concat([frame, pd.DataFrame({'open':[10.]*70, 'high':[11.]*70,
        'low':[9.]*70, 'close':[10.]*70, 'volume':[10000.]*70}, index=dates[90:])])
    summary = WeeklyTrendFacade(tmp_path, '8.0.0').run(
        {'600000': frame}, DesktopBacktestOptions.defaults())
    assert not any('adjustment basis' in str(error) for error in summary.tables['errors'])
