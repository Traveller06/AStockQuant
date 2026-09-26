from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from astock_quant.desktop.weekly_trend_scanner import WeeklyTrendScanner
from astock_quant.desktop.weekly_trend_updater import CachedHistoryUpdater, merge_history


def sample(start='2025-01-02', periods=320, price=10.):
    idx = pd.bdate_range(start, periods=periods)
    return pd.DataFrame({'open':price-.1, 'high':price+.2, 'low':price-.2,
                         'close':price, 'volume':100.}, index=idx)


def test_refresh_writes_overlay_without_touching_existing_cache_and_resumes(tmp_path):
    cache = tmp_path/'cache'
    cache.mkdir()
    original = sample().iloc[:-5]
    original.to_csv(cache/'600000.csv', index_label='date')
    before = (cache/'600000.csv').read_bytes()
    target = sample().index[-1].date()
    calls = []
    def fetch(code):
        calls.append(code)
        return sample()
    updater = CachedHistoryUpdater(tmp_path)
    outcome = updater.refresh(target=target, fetcher=fetch)
    assert outcome.updated == 1 and outcome.failed == 0
    assert (cache/'600000.csv').read_bytes() == before
    assert calls == ['600000']
    assert updater.refresh(target=target, fetcher=fetch).updated == 0
    assert calls == ['600000']
    result = WeeklyTrendScanner(tmp_path, three_tier=True).scan_cache(
        adjustment_basis='qfq', as_of=target)
    assert result.fresh_count == 1 and result.rows[0].latest_date == target.isoformat()


def test_refresh_rejects_old_or_broken_data_and_preserves_existing_overlay(tmp_path):
    cache=tmp_path/'cache'; cache.mkdir()
    old=sample().iloc[:-5]
    old.to_csv(cache/'600000.csv',index_label='date')
    updater=CachedHistoryUpdater(tmp_path)
    target=sample().index[-1].date()
    assert updater.refresh(target=target,fetcher=lambda code: old).failed==1
    assert not (tmp_path/'v8_market_updates/600000.csv').exists()
    good=sample()
    assert updater.refresh(target=target,fetcher=lambda code: good).updated==1
    original=(tmp_path/'v8_market_updates/600000.csv').read_bytes()
    assert updater.refresh(target=date(2026,12,31),fetcher=lambda code: old).failed==1
    assert (tmp_path/'v8_market_updates/600000.csv').read_bytes()==original


def test_scan_without_explicit_date_marks_yesterday_cache_stale_on_saturday(tmp_path, monkeypatch):
    from astock_quant.desktop import weekly_trend_scanner as scanner_module
    (tmp_path/'cache').mkdir()
    frame=sample().iloc[:-1]
    frame.to_csv(tmp_path/'cache/600000.csv',index_label='date')
    monkeypatch.setattr(scanner_module,'_safe_date',lambda now=None: sample().index[-1].date())
    result=WeeklyTrendScanner(tmp_path,three_tier=True).scan_cache(adjustment_basis='qfq')
    assert result.data_as_of==sample().index[-1].date()
    assert result.fresh_count==0 and result.rows[0].status=='stale'


def test_legacy_provider_fetch_only_does_not_change_existing_cache(tmp_path, monkeypatch):
    from windows_app import main
    monkeypatch.setattr(main,'CACHE_DIR',tmp_path)
    monkeypatch.setattr(main.time,'sleep',lambda seconds: None)
    old=sample().iloc[:-5]
    old.to_csv(tmp_path/'600000.csv',index_label='date')
    before=(tmp_path/'600000.csv').read_bytes()
    rows=[[d.strftime('%Y-%m-%d'),'9.9','10','10.2','9.8','100']
          for d in sample().index]
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'data':{'sh600000':{'qfqday':rows}}}
    class Session:
        trust_env=False
        def get(self,*args,**kwargs): return Response()
    monkeypatch.setattr(main.requests,'Session',Session)
    fresh=main.fetch_history('600000',start_year=2025,force_refresh=True,persist=False)
    assert len(fresh)==320
    assert (tmp_path/'600000.csv').read_bytes()==before


def test_qfq_overlay_rebases_prior_prices_at_overlap_boundary():
    old=sample(price=10.)
    fresh=sample(price=9.).iloc[200:]
    merged=merge_history(old,fresh)
    assert merged.iloc[199].close == 9.
    assert merged.iloc[200].close == 9.
    assert merged.index.is_unique
    fresh.iloc[1, fresh.columns.get_loc('close')]=11.
    try:
        merge_history(old,fresh)
    except ValueError as error:
        assert '前复权' in str(error)
    else:
        raise AssertionError('交界处价格因子不一致必须拒绝')


def test_refresh_pause_and_resume_skips_successful_symbols(tmp_path):
    (tmp_path/'cache').mkdir()
    frame=sample()
    for code in ('600000','600001'):
        frame.iloc[:-2].to_csv(tmp_path/'cache'/f'{code}.csv',index_label='date')
    calls=[]
    def fetch(code):
        calls.append(code)
        return frame
    updater=CachedHistoryUpdater(tmp_path)
    target=frame.index[-1].date()
    first=updater.refresh(target=target,fetcher=fetch,should_pause=lambda:len(calls)>=1)
    assert first.paused and first.updated==1 and calls==['600000']
    final=updater.refresh(target=target,fetcher=fetch)
    assert not final.paused and final.updated==1 and final.skipped==1
    assert calls==['600000','600001']


def test_monday_before_close_uses_previous_friday():
    from astock_quant.desktop.weekly_trend_scanner import _safe_date
    now=datetime(2026,9,28,10,tzinfo=ZoneInfo('Asia/Shanghai'))
    assert _safe_date(now)==date(2026,9,25)
