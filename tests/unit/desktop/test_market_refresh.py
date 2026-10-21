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


def test_monday_before_close_skips_mid_autumn_holiday():
    from astock_quant.desktop.weekly_trend_scanner import _safe_date
    now=datetime(2026,9,28,10,tzinfo=ZoneInfo('Asia/Shanghai'))
    assert _safe_date(now)==date(2026,9,24)


def test_index_date_check_accepts_38_valid_rows_without_weakening_stock_history(tmp_path, monkeypatch):
    from windows_app import main
    monkeypatch.setattr(main, 'CACHE_DIR', tmp_path)
    monkeypatch.setattr(main.time, 'sleep', lambda _: None)
    dates = pd.bdate_range(end='2026-09-25', periods=38)
    rows = [[day.strftime('%Y-%m-%d'), '10', '10', '11', '9', '100'] for day in dates]

    class Response:
        def raise_for_status(self): pass
        def json(self): return {'data': {'sh000300': {'qfqday': rows},
                                         'sh600000': {'qfqday': rows}}}

    class Session:
        trust_env = False
        def get(self, *args, **kwargs): return Response()

    monkeypatch.setattr(main.requests, 'Session', Session)
    # Every fallback must be controlled: real providers may return enough history.
    import akshare
    import baostock
    from types import SimpleNamespace
    from astock_quant.data import sina_daily
    short = pd.DataFrame(rows, columns=['date','open','close','high','low','volume'])
    monkeypatch.setattr(sina_daily, 'fetch_sina_daily', lambda *args: short.copy())
    monkeypatch.setattr(akshare, 'stock_zh_a_hist', lambda **kwargs: short.copy())
    monkeypatch.setattr(baostock, 'login', lambda: SimpleNamespace(error_code='1', error_msg='offline fixture'))
    monkeypatch.setattr(baostock, 'logout', lambda: None)
    index = main.fetch_history('INDEX_000300', start_year=2026,
        market_symbol='sh000300', force_refresh=True, persist=False, min_rows=2)
    assert len(index) == 38 and index.index[-1].date() == date(2026,9,25)
    assert not (tmp_path / 'INDEX_000300.csv').exists()
    try:
        main.fetch_history('600000', start_year=2026, force_refresh=True, persist=False)
    except RuntimeError as error:
        assert '不足' in str(error)
    else:
        raise AssertionError('股票默认仍需120行有效历史数据')


def test_short_tencent_history_tries_eastmoney_before_declaring_stock_unavailable(tmp_path, monkeypatch):
    from windows_app import main
    monkeypatch.setattr(main, 'CACHE_DIR', tmp_path)
    monkeypatch.setattr(main.time, 'sleep', lambda _: None)
    short = [[day.strftime('%Y-%m-%d'), '10', '10', '11', '9', '100']
             for day in pd.bdate_range(end='2026-09-25', periods=38)]
    complete = [','.join([day.strftime('%Y-%m-%d'), '10', '10', '11', '9', '100'])
                for day in pd.bdate_range(end='2026-09-25', periods=180)]
    calls = []

    class Response:
        def __init__(self, provider): self.provider = provider
        def raise_for_status(self): pass
        def json(self):
            return ({'data': {'sh600000': {'qfqday': short}}}
                    if self.provider == '腾讯' else {'data': {'klines': complete}})

    class Session:
        trust_env = False
        def get(self, url, *args, **kwargs):
            provider = '腾讯' if 'gtimg' in url else '东方财富'
            calls.append(provider)
            return Response(provider)

    monkeypatch.setattr(main.requests, 'Session', Session)
    result = main.fetch_history('600000', start_year=2026, force_refresh=True, persist=False)
    assert len(result) == 180 and result.attrs['data_source'] == '东方财富直连'
    assert calls == ['腾讯', '东方财富']
    assert not (tmp_path / '600000.csv').exists()


def test_full_market_worker_rejects_old_index_date(tmp_path, monkeypatch):
    from windows_app import main
    from astock_quant.desktop import weekly_trend_scanner
    monkeypatch.setattr(weekly_trend_scanner, '_safe_date', lambda: date(2026,9,25))
    requested = []

    def fetch(*args, **kwargs):
        requested.append(kwargs)
        return sample(start='2026-07-01', periods=30)

    class Scanner:
        def scan(self, **kwargs):
            raise AssertionError('过期指数不能开始全市场选股')

    monkeypatch.setattr(main, 'fetch_history', fetch)
    worker = main.FullMarketWorker(Scanner())
    errors = []
    worker.failed.connect(errors.append)
    worker.run()
    assert requested[0]['min_rows'] == 2
    assert errors and '距离预期收盘日过久' in errors[0]


def test_full_market_worker_accepts_38_recent_index_days(monkeypatch):
    from windows_app import main
    from astock_quant.desktop import weekly_trend_scanner
    monkeypatch.setattr(weekly_trend_scanner, '_safe_date', lambda: date(2026,9,25))
    recent = sample(start='2026-08-05', periods=38)
    # The index only identifies a verified closed day; the stock evaluator
    # retains its independent history and causality requirements.
    recent.index = pd.bdate_range(end='2026-09-25', periods=38)
    monkeypatch.setattr(main, 'fetch_history', lambda *args, **kwargs: recent)

    class Scanner:
        def scan(self, *, target, **kwargs):
            assert target == date(2026,9,25)
            return 'scan-success'

    worker = main.FullMarketWorker(Scanner())
    results = []
    worker.completed.connect(results.append)
    worker.run()
    assert results == ['scan-success']


def test_full_market_worker_failure_identifies_version_and_stage(monkeypatch):
    from windows_app import main
    from astock_quant.desktop import weekly_trend_scanner
    monkeypatch.setattr(weekly_trend_scanner, '_safe_date', lambda: date(2026,9,25))
    monkeypatch.setattr(main, 'fetch_history', lambda *args, **kwargs:
        sample(start='2026-08-01', periods=38).set_axis(
            pd.bdate_range(end='2026-09-25', periods=38)))

    class Scanner:
        def scan(self, **kwargs):
            raise RuntimeError('股票池接口连接中断')

    worker = main.FullMarketWorker(Scanner())
    errors = []
    worker.failed.connect(errors.append)
    worker.run()
    assert errors and main.APP_VERSION in errors[0]
    assert '股票池' in errors[0]


def test_weekly_refresh_uses_short_recent_index_only_for_cutoff(tmp_path, monkeypatch):
    from windows_app.weekly_trend_page import WeeklyRefreshWorker
    from astock_quant.desktop import weekly_trend_scanner
    monkeypatch.setattr(weekly_trend_scanner, '_safe_date', lambda: date(2026,9,25))
    (tmp_path / 'cache').mkdir()
    frame = sample(start='2025-01-02', periods=320)
    frame.iloc[:-2].to_csv(tmp_path / 'cache' / '600000.csv', index_label='date')
    index = frame.iloc[-38:]
    index.index = pd.bdate_range(end='2026-09-25', periods=38)
    refreshed = sample(start='2025-01-02', periods=320)
    refreshed.index = pd.bdate_range(end='2026-09-25', periods=320)
    calls = []

    def fetch(code, **kwargs):
        calls.append((code, kwargs))
        if code == 'INDEX_000300':
            assert kwargs.get('min_rows') == 2
            return index
        return refreshed

    worker = WeeklyRefreshWorker(tmp_path, fetch, None)
    outputs, errors = [], []
    worker.completed.connect(outputs.append)
    worker.failed.connect(errors.append)
    worker.run()
    assert not errors
    assert outputs and outputs[0][0] == date(2026,9,25)


def test_safe_date_skips_official_2026_holidays():
    from astock_quant.desktop.weekly_trend_scanner import _safe_date
    cases = [
        (datetime(2026,10,4,20,14,tzinfo=ZoneInfo('Asia/Shanghai')), date(2026,9,30)),
        (datetime(2026,10,8,15,29,tzinfo=ZoneInfo('Asia/Shanghai')), date(2026,9,30)),
        (datetime(2026,10,8,15,30,tzinfo=ZoneInfo('Asia/Shanghai')), date(2026,10,8)),
        (datetime(2026,10,10,18,tzinfo=ZoneInfo('Asia/Shanghai')), date(2026,10,9)),
        (datetime(2026,2,24,10,tzinfo=ZoneInfo('Asia/Shanghai')), date(2026,2,13)),
        (datetime(2026,1,4,18,tzinfo=ZoneInfo('Asia/Shanghai')), date(2025,12,31)),
        (datetime(2026,4,7,10,tzinfo=ZoneInfo('Asia/Shanghai')), date(2026,4,3)),
        (datetime(2026,5,6,10,tzinfo=ZoneInfo('Asia/Shanghai')), date(2026,4,30)),
        (datetime(2026,6,22,10,tzinfo=ZoneInfo('Asia/Shanghai')), date(2026,6,18)),
        (datetime(2026,10,8,7,30,tzinfo=ZoneInfo('UTC')), date(2026,10,8)),
    ]
    for now, expected in cases:
        assert _safe_date(now) == expected, now


def test_full_market_worker_on_national_holiday_requests_september_close(monkeypatch):
    from windows_app import main
    from astock_quant.desktop import weekly_trend_scanner
    target = weekly_trend_scanner._safe_date(datetime(2026,10,4,20,14,tzinfo=ZoneInfo('Asia/Shanghai')))
    monkeypatch.setattr(weekly_trend_scanner, '_safe_date', lambda: target)
    def fetch(*args, **kwargs):
        assert kwargs['minimum_as_of'] == date(2026,9,30)
        return sample(start='2026-09-29', periods=2)
    class Scanner:
        def scan(self, *, target, **kwargs):
            assert target == date(2026,9,30)
            return 'scan-success'
    monkeypatch.setattr(main, 'fetch_history', fetch)
    worker = main.FullMarketWorker(Scanner())
    results, errors = [], []
    worker.completed.connect(results.append)
    worker.failed.connect(errors.append)
    worker.run()
    assert results == ['scan-success'] and not errors
