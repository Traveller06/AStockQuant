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
