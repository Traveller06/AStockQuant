from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import json

import pandas as pd

from astock_quant.desktop.weekly_trend_scanner import WeeklyTrendScanner, scan_weekly_frames


def rising_setup():
    sessions = [date(2026, 1, 9) + timedelta(days=7 * index) for index in range(25)]
    rows = []
    for index in range(25):
        close = 10.0 + index * 0.4
        rows.append({'open': close - .1,
                     'high': close + (2.0 if index in (5, 12) else .2),
                     'low': close - (2.0 if index in (7, 14) else .2),
                     'close': close, 'volume': 150. if index == 24 else 100.})
    return pd.DataFrame(rows, index=pd.to_datetime(sessions))


def test_real_weekly_setup_is_screened_into_waiting_instead_of_empty():
    frame = rising_setup()
    result = scan_weekly_frames({'600000': frame}, as_of=frame.index[-1].date(),
                                adjustment_basis='qfq', names={'600000': '测试公司'})
    assert result.pool_size == 1
    assert result.data_as_of == frame.index[-1].date()
    assert result.rows[0].status == 'watch'
    assert result.rows[0].name == '测试公司'
    assert result.rows[0].checks
    assert result.signal_count == 0
    assert result.watch_count == 1


def test_stale_and_bad_symbols_cannot_be_screened_as_today_signals():
    frame = rising_setup()
    old = frame.iloc[:-1].copy()
    bad = frame.drop(columns=['open'])
    result = scan_weekly_frames({'600000': frame, '600001': old, '600002': bad},
                                as_of=frame.index[-1].date(), adjustment_basis='qfq')
    assert {row.symbol: row.status for row in result.rows} == {
        '600000': 'watch', '600001': 'stale', '600002': 'error'}
    assert result.fresh_count == 1
    assert result.error_count == 1


def test_future_data_does_not_change_past_screen():
    frame = rising_setup()
    cutoff = frame.index[-1].date()
    altered = pd.concat([frame, pd.DataFrame([{'open':1., 'high':1.1, 'low':.9,
                                               'close':1., 'volume':1e8}],
                                             index=pd.to_datetime(['2026-08-07']))])
    original = scan_weekly_frames({'600000': frame}, as_of=cutoff, adjustment_basis='qfq')
    future = scan_weekly_frames({'600000': altered}, as_of=cutoff, adjustment_basis='qfq')
    assert future.rows == original.rows


def test_scan_requires_explicit_adjustment_basis():
    try:
        scan_weekly_frames({'600000': rising_setup()}, adjustment_basis='')
    except ValueError as error:
        assert '复权' in str(error)
    else:
        raise AssertionError('复权口径不得留空')


def test_cached_pool_scans_read_only_and_reopens_exportable_selection(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    frame = rising_setup()
    frame.to_csv(cache / '600000.csv', index_label='date')
    (cache / 'INDEX_000300.csv').write_text('bad index content', encoding='utf8')
    (tmp_path / 'a_share_universe.json').write_text(json.dumps({
        'stocks': [{'code': '600000', 'name': '浦发银行'}]}, ensure_ascii=False), encoding='utf8')
    original = (cache / '600000.csv').read_bytes()
    scanner = WeeklyTrendScanner(tmp_path)
    result = scanner.scan_cache(adjustment_basis='qfq', as_of=frame.index[-1].date())
    assert result.pool_size == result.fresh_count == result.watch_count == 1
    assert result.rows[0].name == '浦发银行'
    assert scanner.open_last_screen().rows == result.rows
    exported = scanner.export_csv(tmp_path / 'selected.csv')
    assert '浦发银行' in exported.read_text(encoding='utf-8-sig')
    assert (cache / '600000.csv').read_bytes() == original
    assert not (tmp_path / 'tail_strategy_state.json').exists()


def test_monday_partial_week_does_not_replace_last_completed_week():
    prior = rising_setup()
    monday = pd.DataFrame([{'open':19.7, 'high':20.5, 'low':19.6,
                            'close':20.3, 'volume':9000000.}],
                          index=pd.to_datetime(['2026-06-29']))
    result = scan_weekly_frames({'600000': pd.concat([prior, monday])},
                                as_of=date(2026, 6, 29), adjustment_basis='qfq')
    volume = next(item for item in result.rows[0].checks if item['code'] == 'setup.breakout.volume')
    assert volume['actual'] == '150'


def test_real_confirmed_signal_appears_only_after_daily_confirmation():
    prior = rising_setup()
    next_days = pd.DataFrame([
        {'open':19.5, 'high':19.6, 'low':16.6, 'close':17.0, 'volume':100.},
        {'open':17.0, 'high':17.1, 'low':16.5, 'close':16.7, 'volume':100.},
        {'open':16.6, 'high':17.2, 'low':16.6, 'close':16.95, 'volume':200.},
    ], index=pd.to_datetime(['2026-06-29', '2026-06-30', '2026-07-01']))
    frame = pd.concat([prior, next_days])
    tuesday = scan_weekly_frames({'600000': frame},
                                 as_of=date(2026, 6, 30), adjustment_basis='qfq')
    wednesday = scan_weekly_frames({'600000': frame},
                                   as_of=date(2026, 7, 1), adjustment_basis='qfq')
    assert tuesday.signal_count == 0
    assert wednesday.signal_count == 1
    assert wednesday.rows[0].signal_id
