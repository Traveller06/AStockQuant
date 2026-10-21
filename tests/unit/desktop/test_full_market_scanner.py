from datetime import date

import pandas as pd
import pytest
import sys
from types import SimpleNamespace

from astock_quant.desktop.full_market_scanner import FullMarketScanner


TARGET = date(2026, 9, 25)


def bars():
    index = pd.bdate_range(end=TARGET, periods=200)
    return pd.DataFrame({'open': 10., 'high': 11., 'low': 9.,
                         'close': 10., 'volume': 100.}, index=index)


def universe():
    return ([{'code': '600000', 'name': '浦发银行', 'exchange': '沪'},
             {'code': '000001', 'name': '平安银行', 'exchange': '深'},
             {'code': '430001', 'name': '北交样本', 'exchange': '北'},
             {'code': '600001', 'name': '*ST样本', 'exchange': '沪'}], '完整测试列表')


def test_scan_new_and_existing_symbols_and_keep_original_cache(tmp_path):
    (tmp_path / 'cache').mkdir()
    bars().iloc[:-1].to_csv(tmp_path / 'cache' / '600000.csv', index_label='date')
    original = (tmp_path / 'cache' / '600000.csv').read_bytes()
    calls = []

    def fetch(code):
        calls.append(code)
        return bars()

    scanner = FullMarketScanner(tmp_path, universe_loader=universe,
                                history_fetcher=fetch, minimum_pool=3)
    result = scanner.scan(target=TARGET)
    assert result.total == 4 and result.completed == 4 and not result.paused
    assert result.excluded == 1 and result.failed == 0
    assert set(calls) == {'600000', '000001', '430001'}
    assert (tmp_path / 'cache' / '600000.csv').read_bytes() == original
    assert (tmp_path / 'v8_market_updates' / '430001.csv').exists()
    assert scanner.open_last().completed == 4
    assert len(scanner.export_csv(tmp_path / 'scan.csv').read_text(encoding='utf-8-sig').splitlines()) == 5


def test_pause_resume_skips_saved_symbols_and_error_is_retryable(tmp_path):
    calls = []

    def fetch(code):
        calls.append(code)
        if code == '430001' and calls.count(code) == 1:
            raise OSError('暂时断线')
        return bars()

    scanner = FullMarketScanner(tmp_path, universe_loader=universe,
                                history_fetcher=fetch, minimum_pool=3)
    first = scanner.scan(target=TARGET, should_pause=lambda: len(calls) >= 1)
    assert first.paused and first.completed == 1
    second = scanner.scan(target=TARGET)
    assert second.failed == 1 and second.completed == 4
    third = scanner.scan(target=TARGET)
    assert third.failed == 0 and calls.count('000001') == 1
    assert len(calls) == 4


def test_incomplete_market_list_rejected_before_fetch(tmp_path):
    scanner = FullMarketScanner(tmp_path, universe_loader=lambda: (
        [{'code': '600000', 'name': '样本'}], '新浪沪深'),
        history_fetcher=lambda code: pytest.fail('不应读取行情'), minimum_pool=3)
    with pytest.raises(ValueError, match='不完整'):
        scanner.scan(target=TARGET)
    assert not (tmp_path / 'v8_runs').exists()


def test_old_provider_bars_are_not_presented_as_a_current_signal(tmp_path):
    scanner = FullMarketScanner(tmp_path, universe_loader=universe,
                                history_fetcher=lambda code: bars().iloc[:-1], minimum_pool=3)
    result = scanner.scan(target=TARGET)
    assert result.failed == 3 and result.selected == 0


def test_short_stock_history_does_not_abort_other_symbols_and_can_retry(tmp_path):
    attempts = []

    def fetch(code):
        attempts.append(code)
        if code == '000001' and attempts.count(code) == 1:
            raise RuntimeError('有效历史行情不足：38行')
        return bars()

    scanner = FullMarketScanner(tmp_path, universe_loader=universe,
                                history_fetcher=fetch, minimum_pool=3)
    first = scanner.scan(target=TARGET)
    assert first.completed == 4 and first.failed == 1
    assert next(row for row in first.rows if row.symbol == '000001').status == 'error'
    assert (tmp_path / 'v8_market_updates' / '430001.csv').exists()
    retried = scanner.scan(target=TARGET)
    assert retried.completed == 4 and retried.failed == 0
    assert attempts.count('000001') == 2
    assert attempts.count('600000') == 1


def test_full_universe_keeps_st_and_does_not_overwrite_legacy_pool(tmp_path, monkeypatch):
    from windows_app import main
    original = tmp_path / 'a_share_universe.json'
    original.write_text('{"user":"legacy"}', encoding='utf-8')
    monkeypatch.setattr(main, 'UNIVERSE_FILE', original)
    ak = SimpleNamespace(
        stock_info_a_code_name=lambda: pd.DataFrame([
            {'code':'600000','name':'普通股'},
            {'code':'600001','name':'*ST样本'},
            {'code':'000001','name':'深市'},
            {'code':'430001','name':'北交所'}]))
    monkeypatch.setitem(sys.modules, 'akshare', ak)
    stocks, source = main.fetch_market_universe(force=True, include_st=True, persist=False)
    assert len(stocks) == 4 and any(row['name'] == '*ST样本' for row in stocks)
    assert original.read_text(encoding='utf-8') == '{"user":"legacy"}'


def test_short_new_listing_data_saved_and_reported_separately_from_download_failure(tmp_path):
    scanner = FullMarketScanner(tmp_path, universe_loader=universe,
        history_fetcher=lambda code: bars().iloc[-38:] if code == '000001' else bars(), minimum_pool=3)
    result = scanner.scan(target=TARGET)
    row = next(row for row in result.rows if row.symbol == '000001')
    assert row.status == 'insufficient'
    assert row.latest_date == '2026-09-25' and row.close == 10
    assert result.failed == 0
    assert (tmp_path / 'v8_market_updates' / '000001.csv').exists()


def test_all_rows_view_keeps_rejected_and_failed_stocks_visible(tmp_path, monkeypatch):
    from windows_app import main
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main, 'APP_DIR', tmp_path)
    scanner = FullMarketScanner(tmp_path, universe_loader=universe,
        history_fetcher=lambda code: bars().iloc[:-1] if code == '430001' else bars(), minimum_pool=3)
    result = scanner.scan(target=TARGET)
    page = main.KlinePage()
    page.show_full_result(result)
    assert page.full_table.rowCount() == 4
    assert '有效行情 2' in page.full_status.text()
    page.full_filter.setCurrentText('数据失败')
    assert page.full_table.rowCount() == 1
    assert page.full_table.item(0,0).text() == '430001'
    page.full_filter.setCurrentText('入选股票')
    assert page.full_table.rowCount() == 0
    page.close()


def test_beijing_uses_independent_sina_fallback_when_eastmoney_fails(tmp_path, monkeypatch):
    from windows_app import main
    from astock_quant.data import sina_daily
    class Session:
        trust_env = True
        def get(self,*args,**kwargs):
            raise OSError('东方财富断开')
    monkeypatch.setattr(main.requests,'Session',Session)
    monkeypatch.setattr(main,'CACHE_DIR',tmp_path)
    monkeypatch.setattr(main.time,'sleep',lambda _:None)
    monkeypatch.setattr(sina_daily,'fetch_sina_daily', lambda symbol,session,start_year: bars().reset_index(names='date'))
    frame = main.fetch_history('920002', start_year=2026, force_refresh=True, persist=False, min_rows=2)
    assert len(frame) == 200 and frame.attrs['data_source'] == '新浪前复权'


def test_stale_provider_result_is_not_accepted_as_latest_market_date(tmp_path, monkeypatch):
    from windows_app import main
    from astock_quant.data import sina_daily
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'data': {'sh600000':{'qfqday':[['2026-09-23','10','10','11','9','100'],
                                                      ['2026-09-24','10','10','11','9','100']]}}}
    class Session:
        trust_env = False
        def get(self,*args,**kwargs): return Response()
    monkeypatch.setattr(main.requests,'Session',Session)
    monkeypatch.setattr(main,'CACHE_DIR',tmp_path)
    monkeypatch.setattr(main.time,'sleep',lambda _:None)
    monkeypatch.setattr(sina_daily,'fetch_sina_daily',lambda symbol,session,start_year: bars().reset_index(names='date'))
    frame = main.fetch_history('600000',start_year=2026,force_refresh=True,persist=False,
                               min_rows=2,minimum_as_of=TARGET)
    assert frame.index[-1].date() == TARGET and frame.attrs['data_source'] == '新浪前复权'


def test_explicit_historical_cutoff_can_scan_during_a_holiday(monkeypatch):
    from windows_app import main
    from astock_quant.desktop import weekly_trend_scanner
    monkeypatch.setattr(weekly_trend_scanner, '_safe_date', lambda: date(2026,10,1))
    def history(*args, **kwargs):
        assert kwargs['minimum_as_of'] == date(2026,9,25)
        return bars()
    monkeypatch.setattr(main, 'fetch_history', history)
    class Scanner:
        def scan(self, *, target, progress, should_pause): return target
    results, errors = [], []
    worker = main.FullMarketWorker(Scanner(), requested_target=date(2026,9,25))
    worker.completed.connect(results.append)
    worker.failed.connect(errors.append)
    worker.run()
    assert results == [date(2026,9,25)] and not errors


def test_index_date_can_use_independent_sina_when_tencent_and_eastmoney_are_stale(tmp_path, monkeypatch):
    from windows_app import main
    from astock_quant.data import sina_daily
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'data': {'sh000300':{'qfqday':[['2026-09-23','10','10','11','9','100'],
                                                       ['2026-09-24','10','10','11','9','100']]}}}
    class Session:
        trust_env = False
        def get(self,*args,**kwargs): return Response()
    monkeypatch.setattr(main.requests,'Session',Session)
    monkeypatch.setattr(main,'CACHE_DIR',tmp_path)
    monkeypatch.setattr(main.time,'sleep',lambda _:None)
    monkeypatch.setattr(sina_daily,'fetch_sina_index',lambda symbol,session,start_year: bars().reset_index(names='date'), raising=False)
    frame = main.fetch_history('INDEX_000300',market_symbol='sh000300',start_year=2026,
        force_refresh=True,persist=False,min_rows=2,minimum_as_of=TARGET)
    assert frame.index[-1].date() == TARGET and frame.attrs['data_source'] == '新浪指数'


def test_sina_and_independent_bse_can_form_a_complete_market_list(tmp_path,monkeypatch):
    from windows_app import main
    from astock_quant.data import market_universe
    monkeypatch.setitem(sys.modules,'akshare',SimpleNamespace(stock_info_a_code_name=lambda: (_ for _ in ()).throw(OSError('主接口断开'))))
    monkeypatch.setattr(main,'fetch_sina_universe',lambda:[{'code':'600000','name':'沪市'},{'code':'000001','name':'深市'}])
    monkeypatch.setattr(market_universe,'fetch_bse_universe',lambda:[{'code':'920002','name':'北市'}])
    stocks,source=main.fetch_market_universe(force=True,include_st=True,persist=False)
    scanner=FullMarketScanner(tmp_path,universe_loader=lambda:(stocks,source),history_fetcher=lambda code:bars(),minimum_pool=3)
    result=scanner.scan(target=TARGET)
    assert result.total==3 and result.failed==0
    assert {r.symbol for r in result.rows} == {'600000','000001','920002'}


def test_recent_verified_full_manifest_survives_incomplete_live_list(tmp_path):
    previous=FullMarketScanner(tmp_path,universe_loader=universe,history_fetcher=lambda code:bars(),minimum_pool=3)
    previous.scan(target=date(2026,9,24))
    def incomplete(): return ([{'code':'600000','name':'沪市'},{'code':'000001','name':'深市'}], '新浪沪深')
    current=FullMarketScanner(tmp_path,universe_loader=incomplete,history_fetcher=lambda code:bars(),minimum_pool=3)
    result=current.scan(target=TARGET)
    assert result.total==4 and result.completed==4
    assert '名册待更新' in result.source and '2026-09-24' in result.source
    assert result.universe_verified is False and result.universe_as_of == '2026-09-24'
    assert next(r for r in result.rows if r.symbol=='430001').latest_date=='2026-09-25'


def test_old_full_manifest_cannot_be_used_as_current_market_pool(tmp_path):
    old=FullMarketScanner(tmp_path,universe_loader=universe,history_fetcher=lambda code:bars(),minimum_pool=3)
    old.scan(target=date(2026,9,10))
    current=FullMarketScanner(tmp_path,universe_loader=lambda:([], '新浪沪深'),history_fetcher=lambda code:pytest.fail('不应下载'),minimum_pool=3)
    with pytest.raises(ValueError,match='不完整'):
        current.scan(target=TARGET)
