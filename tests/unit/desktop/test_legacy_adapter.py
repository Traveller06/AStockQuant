from datetime import datetime

import pandas as pd
import pytest

from astock_quant.desktop.legacy_adapter import adapt_legacy_frames


def test_legacy_daily_cache_converts_without_changing_source():
    frame = pd.DataFrame({'open':[10.0,11.0], 'high':[11.0,12.0], 'low':[9.5,10.5],
                          'close':[10.5,11.5], 'volume':[100,200]},
                         index=pd.to_datetime(['2026-09-10','2026-09-11']))
    original = frame.copy(deep=True)
    market = adapt_legacy_frames({'600000':frame}, adjustment_basis='qfq', source='v7_cache')
    assert len(market.daily_bars['600000']) == 2
    assert market.daily_bars['600000'][0].timestamp.utcoffset().total_seconds() == 28800
    assert market.daily_bars['600000'][0].amount == 1050.0
    assert market.calendar.sessions[0].isoformat() == '2026-09-10'
    assert market.adjustment_basis == 'forward'
    pd.testing.assert_frame_equal(frame, original)


def test_bad_symbol_is_reported_without_aborting_valid_symbol():
    frame = pd.DataFrame({'open':[10], 'high':[11], 'low':[9], 'close':[10], 'volume':[100]},
                         index=pd.to_datetime(['2026-09-11']))
    market = adapt_legacy_frames({'600000':frame, '600001':frame.drop(columns='open')},
                                  adjustment_basis='qfq', source='v7_cache')
    assert set(market.daily_bars) == {'600000'}
    assert market.issues[0].symbol == '600001'
    assert '字段' in market.issues[0].message_zh


def test_duplicate_and_invalid_dates_are_reported_per_symbol():
    frame = pd.DataFrame({'open':[10,10], 'high':[11,11], 'low':[9,9],
                          'close':[10,10], 'volume':[100,100]},
                         index=['2026-09-11', '2026-09-11'])
    market = adapt_legacy_frames({'600000':frame}, adjustment_basis='qfq', source='v7_cache')
    assert not market.daily_bars
    assert '日期' in market.issues[0].message_zh
    frame.index = ['2026-09-11', 'not-a-date']
    market = adapt_legacy_frames({'600000':frame}, adjustment_basis='qfq', source='v7_cache')
    assert '日期' in market.issues[0].message_zh


def test_missing_adjustment_basis_is_rejected():
    with pytest.raises(ValueError, match='复权'):
        adapt_legacy_frames({}, adjustment_basis='', source='v7_cache')


def test_v7_cache_rejects_incompatible_adjustment_basis():
    with pytest.raises(ValueError, match='前复权'):
        adapt_legacy_frames({}, adjustment_basis='hfq', source='v7_cache')


def test_missing_execution_flags_and_amount_are_identified():
    frame = pd.DataFrame({'open':[10], 'high':[11], 'low':[9], 'close':[10], 'volume':[100]},
                         index=pd.to_datetime(['2026-09-11']))
    market = adapt_legacy_frames({'600000':frame}, adjustment_basis='qfq', source='v7_cache')
    assert market.amount_is_estimated
    assert market.availability_is_unknown
    assert market.execution_bars['600000'][0].bar.timestamp.hour == 9
